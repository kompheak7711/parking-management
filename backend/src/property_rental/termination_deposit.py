"""Current Deposit consequences for an explicitly recorded Lease termination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.lease import LeaseStatus


class TerminationDepositAuthorizationError(PermissionError):
    pass


class TerminationDepositNotFoundError(LookupError):
    pass


class TerminationDepositUnavailableError(RuntimeError):
    pass


class TerminationDepositConsequence(StrEnum):
    NOT_TERMINATED = "NOT_TERMINATED"
    NON_REFUNDABLE_SECURITY = "NON_REFUNDABLE_SECURITY"
    SEPARATE_PET_SETTLEMENT = "SEPARATE_PET_SETTLEMENT"
    SIGNED_TERMS_REVIEW_REQUIRED = "SIGNED_TERMS_REVIEW_REQUIRED"


def _identity(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("A nonzero UUID is required")
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("Response identity is invalid")
    identity = _identity(UUID(value))
    if str(identity) != value:
        raise ValueError("Response identity is invalid")
    return identity


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("Response amount or version is invalid")
    return value


@dataclass(frozen=True, slots=True)
class TerminationDepositBalance:
    deposit_id: UUID
    deposit_type: str
    customer_id: UUID
    version: int
    disposition_state_version: int
    required_usd_cents: int
    received_usd_cents: int
    held_refundable_usd_cents: int
    outstanding_required_usd_cents: int
    active_disposition_usd_cents: int
    consequence: TerminationDepositConsequence
    business_rule: str | None
    explicit_disposition_pending: bool


@dataclass(frozen=True, slots=True)
class TerminationDepositReadiness:
    lease_id: UUID
    property_id: UUID
    observed_at: datetime
    lease_status: str
    actual_termination_date: date | None
    termination_event_id: UUID | None
    evidence_status: str
    deposits: tuple[TerminationDepositBalance, ...]
    currency: str = "USD"
    financial_completion_assessed: bool = False


def parse_termination_deposit_readiness(
    value: object, *, lease_id: UUID, property_id: UUID
) -> TerminationDepositReadiness:
    """Validate the bounded read contract without authorizing a money command."""
    try:
        if not isinstance(value, dict) or set(value) != {
            "lease_id",
            "property_id",
            "observed_at",
            "lease_status",
            "actual_termination_date",
            "termination_event_id",
            "evidence_status",
            "deposits",
            "currency",
            "financial_completion_assessed",
        }:
            raise ValueError("Response shape is invalid")
        if _uuid(value["lease_id"]) != lease_id or _uuid(value["property_id"]) != property_id:
            raise ValueError("Response scope is invalid")
        observed = value["observed_at"]
        if not isinstance(observed, str):
            raise ValueError("Observation timestamp is invalid")
        observed_at = datetime.fromisoformat(observed)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("Observation timestamp needs a timezone")
        status, evidence = value["lease_status"], value["evidence_status"]
        if status not in {item.value for item in LeaseStatus} or evidence not in {
            "NO_TERMINATION",
            "VOLUNTARY_EARLY_VERIFIED",
            "SIGNED_TERMS_REVIEW_REQUIRED",
        }:
            raise ValueError("Termination evidence status is invalid")
        actual_raw = value["actual_termination_date"]
        actual = None
        if actual_raw is not None:
            if not isinstance(actual_raw, str):
                raise ValueError("Actual termination date is invalid")
            actual = date.fromisoformat(actual_raw)
            if actual.isoformat() != actual_raw:
                raise ValueError("Actual termination date is invalid")
        event = (
            None if value["termination_event_id"] is None else _uuid(value["termination_event_id"])
        )
        if (status == "TERMINATED") != (actual is not None):
            raise ValueError("Actual termination state is inconsistent")
        if (evidence == "NO_TERMINATION") != (status != "TERMINATED"):
            raise ValueError("Termination evidence is inconsistent")
        if status != "TERMINATED" and event is not None:
            raise ValueError("An unterminated Lease cannot have termination evidence")
        if evidence == "VOLUNTARY_EARLY_VERIFIED" and event is None:
            raise ValueError("Verified termination requires a real event")
        if value["currency"] != "USD" or value["financial_completion_assessed"] is not False:
            raise ValueError("Unsupported financial completion or currency claim")
        rows = value["deposits"]
        if not isinstance(rows, list) or len(rows) > 2:
            raise ValueError("Deposit response is not bounded")
        deposits: list[TerminationDepositBalance] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "deposit_id",
                "deposit_type",
                "customer_id",
                "version",
                "disposition_state_version",
                "required_usd_cents",
                "received_usd_cents",
                "held_refundable_usd_cents",
                "outstanding_required_usd_cents",
                "active_disposition_usd_cents",
                "consequence",
                "business_rule",
                "explicit_disposition_pending",
            }:
                raise ValueError("Deposit shape is invalid")
            kind = row["deposit_type"]
            if kind not in {"SECURITY", "PET"}:
                raise ValueError("Deposit type is invalid")
            amounts = {
                key: _integer(row[key])
                for key in (
                    "required_usd_cents",
                    "received_usd_cents",
                    "held_refundable_usd_cents",
                    "outstanding_required_usd_cents",
                    "active_disposition_usd_cents",
                )
            }
            if (
                amounts["outstanding_required_usd_cents"]
                != max(amounts["required_usd_cents"] - amounts["received_usd_cents"], 0)
                or amounts["held_refundable_usd_cents"] + amounts["active_disposition_usd_cents"]
                > amounts["received_usd_cents"]
            ):
                raise ValueError("Deposit balances are inconsistent")
            expected = TerminationDepositConsequence.SIGNED_TERMS_REVIEW_REQUIRED
            rule = None
            if status != "TERMINATED":
                expected = TerminationDepositConsequence.NOT_TERMINATED
            elif evidence == "VOLUNTARY_EARLY_VERIFIED":
                expected = (
                    TerminationDepositConsequence.NON_REFUNDABLE_SECURITY
                    if kind == "SECURITY"
                    else TerminationDepositConsequence.SEPARATE_PET_SETTLEMENT
                )
                rule = "BR-DEP-023" if kind == "SECURITY" else "BR-DEP-024"
            pending = (
                expected is TerminationDepositConsequence.NON_REFUNDABLE_SECURITY
                and amounts["held_refundable_usd_cents"] > 0
            )
            if (
                row["consequence"] != expected.value
                or row["business_rule"] != rule
                or row["explicit_disposition_pending"] is not pending
            ):
                raise ValueError("Deposit consequence is inconsistent")
            version = _integer(row["version"], minimum=1)
            financial_version = _integer(row["disposition_state_version"], minimum=version)
            if financial_version > 2**63 - 1:
                raise ValueError("Financial revision exceeds bigint")
            deposits.append(
                TerminationDepositBalance(
                    deposit_id=_uuid(row["deposit_id"]),
                    deposit_type=kind,
                    customer_id=_uuid(row["customer_id"]),
                    version=version,
                    disposition_state_version=financial_version,
                    required_usd_cents=amounts["required_usd_cents"],
                    received_usd_cents=amounts["received_usd_cents"],
                    held_refundable_usd_cents=amounts["held_refundable_usd_cents"],
                    outstanding_required_usd_cents=amounts["outstanding_required_usd_cents"],
                    active_disposition_usd_cents=amounts["active_disposition_usd_cents"],
                    consequence=expected,
                    business_rule=rule,
                    explicit_disposition_pending=pending,
                )
            )
        if len({d.deposit_id for d in deposits}) != len(deposits) or len(
            {d.deposit_type for d in deposits}
        ) != len(deposits):
            raise ValueError("Deposit identities or types are duplicated")
        return TerminationDepositReadiness(
            lease_id, property_id, observed_at, status, actual, event, evidence, tuple(deposits)
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise TerminationDepositUnavailableError("Termination Deposit response is invalid") from exc


@dataclass(frozen=True, slots=True)
class PostgresTerminationDepositReadService:
    database_url: str
    property_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id)

    def get(self, lease_id: UUID, *, actor: AuthenticatedActor) -> TerminationDepositReadiness:
        _identity(lease_id)
        try:
            actor_id = _identity(UUID(actor.actor_id))
            if not all(
                is_authorized(actor, AuthorizationRequirement(capability, str(self.property_id)))
                for capability in ("leases.read", "deposits.read")
            ):
                raise ValueError("Both scoped read capabilities are required")
        except (ValueError, TypeError, AttributeError) as exc:
            raise TerminationDepositAuthorizationError(
                "Termination Deposit read is not authorized"
            ) from exc
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                row = connection.execute(
                    "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)",
                    (self.property_id, lease_id, actor_id),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"42501", "P5406"}:
                raise TerminationDepositAuthorizationError(
                    "Termination Deposit actor is not active"
                ) from exc
            if exc.sqlstate in {"P0002", "P5401"}:
                raise TerminationDepositNotFoundError(
                    "Termination Deposit resource was not found"
                ) from exc
            raise TerminationDepositUnavailableError(
                "Termination Deposit read is unavailable"
            ) from exc
        if row is None or len(row) != 1:
            raise TerminationDepositUnavailableError("Termination Deposit response is missing")
        return parse_termination_deposit_readiness(
            cast(object, row[0]), lease_id=lease_id, property_id=self.property_id
        )
