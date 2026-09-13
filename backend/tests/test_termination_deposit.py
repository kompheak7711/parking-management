"""Validate the bounded termination read without authorizing financial actions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import cast
from uuid import UUID

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.termination_deposit import (
    PostgresTerminationDepositReadService,
    TerminationDepositAuthorizationError,
    TerminationDepositConsequence,
    TerminationDepositNotFoundError,
    TerminationDepositUnavailableError,
    parse_termination_deposit_readiness,
)

LEASE, PROPERTY, HUMAN = UUID(int=1), UUID(int=2), UUID(int=3)


def payload() -> dict[str, object]:
    return {
        "lease_id": str(LEASE),
        "property_id": str(PROPERTY),
        "observed_at": "2026-09-14T02:00:00+00:00",
        "lease_status": "TERMINATED",
        "actual_termination_date": "2026-09-14",
        "termination_event_id": str(UUID(int=4)),
        "evidence_status": "VOLUNTARY_EARLY_VERIFIED",
        "currency": "USD",
        "financial_completion_assessed": False,
        "deposits": [
            {
                "deposit_id": str(UUID(int=5)),
                "deposit_type": "SECURITY",
                "customer_id": str(UUID(int=6)),
                "version": 2,
                "required_usd_cents": 50_000,
                "received_usd_cents": 10_000,
                "held_refundable_usd_cents": 10_000,
                "outstanding_required_usd_cents": 40_000,
                "active_disposition_usd_cents": 0,
                "consequence": "NON_REFUNDABLE_SECURITY",
                "business_rule": "BR-DEP-023",
                "explicit_disposition_pending": True,
            }
        ],
    }


def balance(value: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], value["deposits"])[0]


def read_actor(*capabilities: str, prop: UUID = PROPERTY) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(HUMAN),
        frozenset(CapabilityGrant(name, frozenset({str(prop)})) for name in capabilities),
    )


def test_current_read_separates_required_cash_and_disposition_and_is_immutable() -> None:
    result = parse_termination_deposit_readiness(payload(), lease_id=LEASE, property_id=PROPERTY)
    item = result.deposits[0]
    assert (
        item.required_usd_cents,
        item.received_usd_cents,
        item.outstanding_required_usd_cents,
    ) == (50_000, 10_000, 40_000)
    assert item.explicit_disposition_pending and not result.financial_completion_assessed
    assert item.consequence is TerminationDepositConsequence.NON_REFUNDABLE_SECURITY
    assert result.observed_at.utcoffset() is not None
    for attribute, value in (("received_usd_cents", 50_000), ("version", 3)):
        with pytest.raises(FrozenInstanceError):
            setattr(item, attribute, value)


@pytest.mark.parametrize(
    "kind,held,received,disposed",
    [
        ("SECURITY", 0, 0, 0),
        ("SECURITY", 0, 10_000, 10_000),
        ("SECURITY", 4_000, 10_000, 6_000),
        ("PET", 10_000, 10_000, 0),
    ],
)
def test_current_zero_is_not_financial_completion_and_pet_is_separate(
    kind: str,
    held: int,
    received: int,
    disposed: int,
) -> None:
    value = payload()
    row = balance(value)
    row.update(
        deposit_type=kind,
        held_refundable_usd_cents=held,
        received_usd_cents=received,
        outstanding_required_usd_cents=50_000 - received,
        active_disposition_usd_cents=disposed,
        explicit_disposition_pending=kind == "SECURITY" and held > 0,
    )
    if kind == "PET":
        row.update(consequence="SEPARATE_PET_SETTLEMENT", business_rule="BR-DEP-024")
    result = parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)
    assert not result.financial_completion_assessed
    assert result.deposits[0].held_refundable_usd_cents == held


@pytest.mark.parametrize("status", ["DRAFTED", "SIGNED", "CANCELLED"])
def test_every_unterminated_lease_status_has_no_termination_consequence(status: str) -> None:
    value = payload()
    value.update(
        lease_status=status,
        actual_termination_date=None,
        termination_event_id=None,
        evidence_status="NO_TERMINATION",
    )
    balance(value).update(
        consequence="NOT_TERMINATED", business_rule=None, explicit_disposition_pending=False
    )
    result = parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)
    assert result.lease_status == status
    assert result.deposits[0].consequence is TerminationDepositConsequence.NOT_TERMINATED


@pytest.mark.parametrize(
    "key,bad",
    [
        ("lease_id", str(UUID(int=7))),
        ("property_id", str(UUID(int=7))),
        ("observed_at", "2026-09-14T02:00:00"),
        ("observed_at", 123),
        ("lease_status", "DRAFT"),
        ("lease_status", []),
        ("actual_termination_date", None),
        ("actual_termination_date", "20260914"),
        ("termination_event_id", None),
        ("termination_event_id", str(UUID(int=0))),
        ("evidence_status", "NO_TERMINATION"),
        ("evidence_status", "TRUST_REASON"),
        ("currency", "KHR"),
        ("financial_completion_assessed", True),
        ("financial_completion_assessed", 0),
        ("deposits", {}),
        ("unknown_field", "extra"),
    ],
)
def test_malformed_or_cross_scope_response_is_unavailable(key: str, bad: object) -> None:
    value = payload()
    value[key] = bad
    with pytest.raises(TerminationDepositUnavailableError):
        parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("deposit_id", str(UUID(int=0))),
        ("customer_id", "invalid"),
        ("version", 0),
        ("version", True),
        ("deposit_type", "CREDIT"),
        ("required_usd_cents", -1),
        ("received_usd_cents", 10_000.0),
        ("held_refundable_usd_cents", True),
        ("active_disposition_usd_cents", 1),
        ("outstanding_required_usd_cents", 0),
        ("consequence", "SEPARATE_PET_SETTLEMENT"),
        ("business_rule", "BR-DEP-022"),
        ("explicit_disposition_pending", 1),
        ("unknown_field", "extra"),
    ],
)
def test_malformed_balance_or_invented_consequence_is_unavailable(key: str, bad: object) -> None:
    value = payload()
    balance(value)[key] = bad
    with pytest.raises(TerminationDepositUnavailableError):
        parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)


@pytest.mark.parametrize("count", [2, 3])
def test_duplicate_or_unbounded_deposits_are_not_silently_accepted(count: int) -> None:
    value = payload()
    value["deposits"] = [deepcopy(balance(value)) for _ in range(count)]
    with pytest.raises(TerminationDepositUnavailableError):
        parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)


def test_unverified_signed_basis_never_invents_a_disposition() -> None:
    value = payload()
    value.update(evidence_status="SIGNED_TERMS_REVIEW_REQUIRED", termination_event_id=None)
    balance(value).update(
        consequence="SIGNED_TERMS_REVIEW_REQUIRED",
        business_rule=None,
        explicit_disposition_pending=False,
    )
    result = parse_termination_deposit_readiness(value, lease_id=LEASE, property_id=PROPERTY)
    assert not result.deposits[0].explicit_disposition_pending


@pytest.mark.parametrize(
    "capabilities,prop",
    [
        ((), PROPERTY),
        (("leases.read",), PROPERTY),
        (("deposits.read",), PROPERTY),
        (("leases.read", "deposits.read"), UUID(int=8)),
    ],
)
def test_both_property_capabilities_are_required_before_opening_a_connection(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: tuple[str, ...],
    prop: UUID,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Denied capability must not open a connection")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    with pytest.raises(TerminationDepositAuthorizationError):
        PostgresTerminationDepositReadService("unused", PROPERTY).get(
            LEASE, actor=read_actor(*capabilities, prop=prop)
        )


@pytest.mark.parametrize(
    "state,error",
    [
        ("P5406", TerminationDepositAuthorizationError),
        ("42501", TerminationDepositAuthorizationError),
        ("P5401", TerminationDepositNotFoundError),
        ("P0002", TerminationDepositNotFoundError),
        ("08006", TerminationDepositUnavailableError),
        ("P5501", TerminationDepositUnavailableError),
    ],
)
def test_read_database_failures_are_mapped_without_returning_source_data(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    error: type[Exception],
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise type("ReadFailure", (psycopg.Error,), {"sqlstate": state})(
            "synthetic internal detail"
        )

    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(error) as failure:
        PostgresTerminationDepositReadService("unused", PROPERTY).get(
            LEASE, actor=read_actor("leases.read", "deposits.read")
        )
    assert "synthetic internal detail" not in str(failure.value)
