"""Explicit signed-Lease evidence for an authorized termination command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class TerminationBasis(StrEnum):
    VOLUNTARY_EARLY = "VOLUNTARY_EARLY"
    CUSTOMER_VIOLATION = "CUSTOMER_VIOLATION"
    SIGNED_LEASE_OTHER = "SIGNED_LEASE_OTHER"
    UNPAID_INITIAL_OBLIGATION = "UNPAID_INITIAL_OBLIGATION"


def _text(value: object, field: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or "\x00" in value
    ):
        raise ValueError(f"{field} must be normalized, nonblank, and bounded")


@dataclass(frozen=True, slots=True)
class TerminationContext:
    """Documented authority, never an automatically created termination right."""

    basis: TerminationBasis
    signed_lease_provision: str
    approved_grounds: str
    management_authorization_reference: str
    evidence_reference: str
    notice_required: bool
    notice_id: UUID | None = None
    notice_period_ends_on: date | None = None
    notice_exception_reason: str | None = None
    warning_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.basis, TerminationBasis):
            raise ValueError("Termination basis must be explicit")
        for field, maximum in (
            ("signed_lease_provision", 2000),
            ("approved_grounds", 2000),
            ("management_authorization_reference", 500),
            ("evidence_reference", 500),
        ):
            _text(getattr(self, field), field, maximum)
        if type(self.notice_required) is not bool:
            raise ValueError("Notice applicability must be explicit")
        if self.notice_required:
            if (
                not isinstance(self.notice_id, UUID)
                or self.notice_id.int == 0
                or type(self.notice_period_ends_on) is not date
                or self.notice_exception_reason is not None
            ):
                raise ValueError("Applicable notice needs its identity and documented period end")
        else:
            if self.notice_id is not None or self.notice_period_ends_on is not None:
                raise ValueError("A notice exception cannot also supply an applicable notice")
            _text(self.notice_exception_reason, "notice_exception_reason", 2000)
        if (
            type(self.warning_ids) is not tuple
            or len(self.warning_ids) > 100
            or any(not isinstance(value, UUID) or value.int == 0 for value in self.warning_ids)
            or len(set(self.warning_ids)) != len(self.warning_ids)
        ):
            raise ValueError("Warning identities must be bounded, distinct, nonzero UUIDs")
        if self.basis is TerminationBasis.CUSTOMER_VIOLATION:
            if len(self.warning_ids) < 3:
                raise ValueError("Violation termination needs at least three general warnings")
        elif self.warning_ids:
            raise ValueError("General warning prerequisites apply to violation termination")

    def validate_command(self, actual_date: date, governing_reference: str) -> None:
        if type(actual_date) is not date:
            raise ValueError("Actual termination date must be a calendar date")
        voluntary = self.basis is TerminationBasis.VOLUNTARY_EARLY
        if voluntary != (governing_reference == "BR-LEASE-021"):
            raise ValueError("Governing event must match the approved termination basis")
        if (
            self.basis is TerminationBasis.UNPAID_INITIAL_OBLIGATION
            and governing_reference != "BR-LEASE-005"
        ):
            raise ValueError("Governing event must match the approved termination basis")
        if self.notice_period_ends_on is not None and actual_date < self.notice_period_ends_on:
            raise ValueError("Actual termination cannot precede the documented notice period end")

    def intent(self) -> dict[str, object]:
        return {
            "basis": self.basis.value,
            "signed_lease_provision": self.signed_lease_provision,
            "approved_grounds": self.approved_grounds,
            "management_authorization_reference": self.management_authorization_reference,
            "evidence_reference": self.evidence_reference,
            "notice_required": self.notice_required,
            "notice_id": str(self.notice_id) if self.notice_id is not None else None,
            "notice_period_ends_on": (
                self.notice_period_ends_on.isoformat()
                if self.notice_period_ends_on is not None
                else None
            ),
            "notice_exception_reason": self.notice_exception_reason,
            "warning_ids": [str(value) for value in self.warning_ids],
        }
