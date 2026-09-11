"""Authorized notice evidence; recording a notice never terminates a Lease."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

NOTICE_READ = "leases.read"
NOTICE_RECORD = "leases.terminate"


class LeaseNoticeNotFoundError(LookupError):
    pass


class LeaseNoticeAuthorizationError(PermissionError):
    pass


class LeaseNoticeInvalidError(ValueError):
    pass


class LeaseNoticeConflictError(RuntimeError):
    pass


class LeaseNoticeKeyReused(LeaseNoticeConflictError):
    pass


class LeaseNoticeUnavailableError(RuntimeError):
    """Keep the exact command for recovery when its outcome is uncertain."""


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise LeaseNoticeInvalidError(f"{field} must be a nonzero UUID")


@dataclass(frozen=True, slots=True)
class RecordLeaseNotice:
    idempotency_key: UUID
    notice_id: UUID
    expected_lease_version: int
    notice_date: date
    intended_termination_date: date | None
    notice_text: str
    governing_lease_provision: str
    approved_grounds: str
    notice_period_terms: str
    evidence_reference: str
    communication_record: str
    authorization_reference: str
    reason: str
    supersedes_notice_id: UUID | None = None

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.notice_id, "notice_id")
        if self.supersedes_notice_id is not None:
            _identity(self.supersedes_notice_id, "supersedes_notice_id")
            if self.supersedes_notice_id == self.notice_id:
                raise LeaseNoticeInvalidError("A correction must reference an earlier notice")
        if (
            type(self.expected_lease_version) is not int
            or not 1 <= self.expected_lease_version <= 2_147_483_647
        ):
            raise LeaseNoticeInvalidError("Expected Lease version must be a positive integer")
        if type(self.notice_date) is not date or (
            self.intended_termination_date is not None
            and type(self.intended_termination_date) is not date
        ):
            raise LeaseNoticeInvalidError("Notice dates must be calendar dates")
        if (
            self.intended_termination_date is not None
            and self.intended_termination_date < self.notice_date
        ):
            raise LeaseNoticeInvalidError("The intended date cannot precede the notice")
        for field, maximum in (
            ("notice_text", 5000),
            ("governing_lease_provision", 2000),
            ("approved_grounds", 2000),
            ("notice_period_terms", 2000),
            ("evidence_reference", 500),
            ("communication_record", 2000),
            ("authorization_reference", 500),
            ("reason", 500),
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= maximum
                or value != value.strip()
                or "\x00" in value
            ):
                raise LeaseNoticeInvalidError(f"{field} must be normalized and bounded")

    def intent(self) -> dict[str, object]:
        return {
            "notice_id": str(self.notice_id),
            "expected_lease_version": self.expected_lease_version,
            "notice_date": self.notice_date.isoformat(),
            "intended_termination_date": (
                self.intended_termination_date.isoformat()
                if self.intended_termination_date is not None
                else None
            ),
            "notice_text": self.notice_text,
            "governing_lease_provision": self.governing_lease_provision,
            "approved_grounds": self.approved_grounds,
            "notice_period_terms": self.notice_period_terms,
            "evidence_reference": self.evidence_reference,
            "communication_record": self.communication_record,
            "authorization_reference": self.authorization_reference,
            "reason": self.reason,
            "supersedes_notice_id": (
                str(self.supersedes_notice_id) if self.supersedes_notice_id is not None else None
            ),
        }


def notice_request_digest(property_id: UUID, lease_id: UUID, intent: dict[str, object]) -> str:
    body = {
        "action": "lease.notice.record",
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class LeaseNoticeResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresLeaseNoticeService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, write: bool) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise LeaseNoticeAuthorizationError("Notice actor is invalid") from exc
        capability = NOTICE_RECORD if write else NOTICE_READ
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if not write:
                raise LeaseNoticeNotFoundError("Lease notice resource was not found")
            raise LeaseNoticeAuthorizationError("Recording a notice is not authorized")
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        # Only explicit pre-write business errors establish a definite rejection.
        if error.sqlstate in {"P5501", "P5401"}:
            return LeaseNoticeNotFoundError("Lease notice resource was not found")
        if error.sqlstate == "P5502":
            return LeaseNoticeInvalidError("Lease notice request is invalid")
        if error.sqlstate == "P5503":
            return LeaseNoticeConflictError("Lease or notice evidence changed; refresh it")
        if error.sqlstate == "P5505":
            return LeaseNoticeKeyReused("Lease notice command key was reused")
        if error.sqlstate in {"P5506", "P5406"}:
            return LeaseNoticeAuthorizationError("Lease notice actor is not active")
        return LeaseNoticeUnavailableError("Lease notice persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise LeaseNoticeUnavailableError("Lease notice persistence is unavailable")
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.read_only = not write
                connection.execute("SELECT set_config('lock_timeout','3000',true)")
                connection.execute("SELECT set_config('statement_timeout','5000',true)")
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise self._error(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise LeaseNoticeUnavailableError("Lease notice result is unavailable")
        return cast(dict[str, object], row[0])

    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        _identity(lease_id, "lease_id")
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise LeaseNoticeInvalidError("Notice page is invalid")
        actor_id = self._authorize(actor, property_id, write=False)
        return self._query(
            "SELECT app.lease_notice_read(%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, limit, offset),
            write=False,
        )

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordLeaseNotice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseNoticeResponse:
        _identity(lease_id, "lease_id")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise LeaseNoticeInvalidError("request_id is invalid")
        actor_id = self._authorize(actor, property_id, write=True)
        intent = command.intent()
        result = self._query(
            "SELECT app.lease_notice_record(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                actor_id,
                command.idempotency_key,
                notice_request_digest(property_id, lease_id, intent),
                Jsonb(intent),
                request_id,
            ),
            write=True,
        )
        body = result.get("body")
        if (
            result.get("status_code") != 201
            or not isinstance(body, dict)
            or not isinstance(body.get("data"), dict)
        ):
            raise LeaseNoticeUnavailableError("Lease notice command result is unavailable")
        return LeaseNoticeResponse(201, cast(dict[str, object], body))
