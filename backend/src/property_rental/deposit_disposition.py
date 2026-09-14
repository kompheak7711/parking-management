"""Exact approved termination source and financial observation for a new disposition."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class DepositDispositionRule(StrEnum):
    PET_NONCOMPLIANCE = "BR-DEP-022"
    VOLUNTARY_SECURITY = "BR-DEP-023"


@dataclass(frozen=True, slots=True)
class LeaseDepositDispositionContext:
    termination_event_id: UUID
    governing_rule: DepositDispositionRule
    expected_state_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.termination_event_id, UUID) or self.termination_event_id.int == 0:
            raise ValueError("Termination event must be a nonzero UUID")
        if not isinstance(self.governing_rule, DepositDispositionRule):
            raise ValueError("Deposit governing rule must be explicit and supported")
        if type(self.expected_state_version) is not int or not (
            0 < self.expected_state_version <= 2**63 - 1
        ):
            raise ValueError("Expected financial revision must be a positive bigint integer")
