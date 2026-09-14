"""Strict source intent, historical digest continuity and protected service routing."""

import hashlib
import json
from dataclasses import asdict, replace
from datetime import date
from typing import cast
from uuid import UUID

import psycopg
import pytest

from property_rental.deposit import (
    DepositAuthorizationError,
    DepositConflictError,
    DepositSnapshot,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    deposit_request_digest,
)
from property_rental.deposit_disposition import (
    DepositDispositionRule,
    LeaseDepositDispositionContext,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def context() -> LeaseDepositDispositionContext:
    return LeaseDepositDispositionContext(UUID(int=5), DepositDispositionRule.VOLUNTARY_SECURITY, 9)


def command() -> RecordDepositDispositionCommand:
    return RecordDepositDispositionCommand(
        UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 100, date(2027, 1, 1), "Approved"
    )


@pytest.mark.parametrize("value", [None, "event", str(UUID(int=5)), UUID(int=0), 5])
def test_context_requires_actual_nonzero_termination_uuid(value: object) -> None:
    with pytest.raises(ValueError, match="UUID"):
        replace(context(), termination_event_id=cast(UUID, value))


@pytest.mark.parametrize("value", [None, "BR-DEP-023", "BR-DEP-024", "BR-DEP-999", 1])
def test_context_rule_is_typed_and_explicit(value: object) -> None:
    with pytest.raises(ValueError, match="rule"):
        replace(context(), governing_rule=cast(DepositDispositionRule, value))


@pytest.mark.parametrize("value", [None, True, False, "1", 1.0, 0, -1, 2**63])
def test_financial_revision_is_a_positive_exact_bigint(value: object) -> None:
    with pytest.raises(ValueError, match="revision"):
        replace(context(), expected_state_version=cast(int, value))


@pytest.mark.parametrize("value", [1, 2**63 - 1])
def test_financial_revision_accepts_both_valid_boundaries(value: int) -> None:
    assert replace(context(), expected_state_version=value).expected_state_version == value


def test_absent_context_digest_matches_original_wire_shape_byte_for_byte() -> None:
    value = command()
    original = {
        "idempotency_key": value.idempotency_key,
        "disposition_id": value.disposition_id,
        "deposit_id": value.deposit_id,
        "governing_lease_id": value.governing_lease_id,
        "amount_usd_cents": value.amount_usd_cents,
        "effective_date": value.effective_date,
        "reason": value.reason,
        "authorization_reference": value.authorization_reference,
    }
    payload = json.dumps(
        {"action": "deposit.disposition.record", "command": original},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert (
        deposit_request_digest("deposit.disposition.record", value)
        == hashlib.sha256(payload.encode()).hexdigest()
    )


def test_digest_binds_context_and_each_original_request_field() -> None:
    value = replace(command(), context=context())
    digest = deposit_request_digest("deposit.disposition.record", value)
    changes: list[RecordDepositDispositionCommand] = [
        replace(value, idempotency_key=UUID(int=11)),
        replace(value, disposition_id=UUID(int=12)),
        replace(value, deposit_id=UUID(int=13)),
        replace(value, governing_lease_id=UUID(int=14)),
        replace(value, amount_usd_cents=101),
        replace(value, effective_date=date(2027, 1, 2)),
        replace(value, reason="Other approved decision"),
        replace(value, authorization_reference="other"),
        replace(value, context=replace(context(), termination_event_id=UUID(int=15))),
        replace(
            value,
            context=replace(context(), governing_rule=DepositDispositionRule.PET_NONCOMPLIANCE),
        ),
        replace(value, context=replace(context(), expected_state_version=10)),
        replace(value, context=None),
    ]
    assert all(
        deposit_request_digest("deposit.disposition.record", change) != digest for change in changes
    )
    assert asdict(value)["context"] is not None


def test_context_bearing_command_rejects_untyped_context_and_unbounded_reason() -> None:
    with pytest.raises(ValueError, match="typed"):
        replace(command(), context=cast(LeaseDepositDispositionContext, {}))
    for reason in ("x" * 1001, "null\x00text"):
        with pytest.raises(ValueError, match="bounded"):
            replace(command(), context=context(), reason=reason)


@pytest.mark.parametrize("legacy", [True, False])
def test_service_preserves_legacy_route_and_sends_complete_explicit_context(
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
) -> None:
    result = cast(DepositSnapshot, object())
    calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(
        self: PostgresDepositService, query: str, params: tuple[object, ...]
    ) -> DepositSnapshot:
        calls.append((query, params))
        return result

    monkeypatch.setattr(PostgresDepositService, "_execute", execute)
    service = PostgresDepositService("unused", UUID(int=7), UUID(int=8))
    actor = AuthenticatedActor(
        str(service.actor_id),
        frozenset({CapabilityGrant("deposits.dispose", frozenset({str(service.property_id)}))}),
    )
    value = command() if legacy else replace(command(), context=context())
    assert service.record_disposition(value, actor=actor) is result
    assert len(calls) == 1 and len(calls[0][1]) == (11 if legacy else 14)
    assert ("_with_context(" in calls[0][0]) is (not legacy)
    if not legacy:
        assert calls[0][1][-3:] == (UUID(int=5), DepositDispositionRule.VOLUNTARY_SECURITY, 9)
    calls.clear()
    with pytest.raises(DepositAuthorizationError):
        service.record_disposition(value, actor=replace(actor, capability_grants=frozenset()))
    assert calls == []


@pytest.mark.parametrize("sqlstate", ["P5801", "40001"])
def test_stale_observation_and_serialization_failure_are_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str,
) -> None:
    class Conflict(psycopg.Error):
        pass

    failure = Conflict("Synthetic stale observation")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    service = PostgresDepositService("unused", UUID(int=7), UUID(int=8))
    with pytest.raises(DepositConflictError):
        service._execute("unused", ())
