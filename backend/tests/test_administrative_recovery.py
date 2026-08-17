"""Focused deterministic tests for administrative recovery authorization."""

from dataclasses import fields
from datetime import UTC, datetime
from typing import cast

import pytest

from property_rental.administrative_recovery import (
    AdministrativeRecoveryAuthorizationService,
    RecoveryAccount,
    RecoveryAuthorizationAuditEvidence,
    RecoveryAuthorizationReason,
)


class CollectingRecoveryAuthorizationAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryAuthorizationAuditEvidence] = []

    def record(self, evidence: RecoveryAuthorizationAuditEvidence) -> None:
        self.evidence.append(evidence)


OCCURRED_AT = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


def authorize(
    *,
    actor_class: str,
    target_class: str,
    actor_id: str = "actor-2i",
    target_id: str = "target-2i",
) -> tuple[bool, RecoveryAuthorizationAuditEvidence]:
    audit_sink = CollectingRecoveryAuthorizationAuditSink()
    decision = AdministrativeRecoveryAuthorizationService(
        clock=lambda: OCCURRED_AT,
        audit_sink=audit_sink,
    ).authorize(
        actor=RecoveryAccount(account_id=actor_id, account_class=actor_class),
        target=RecoveryAccount(account_id=target_id, account_class=target_class),
        correlation_id="correlation-2i",
    )
    return decision.allowed, audit_sink.evidence[0]


@pytest.mark.parametrize(
    ("actor_class", "target_class", "allowed", "reason"),
    [
        ("owner", "manager", True, "owner_to_manager"),
        ("owner", "staff", True, "owner_to_staff"),
        ("staff", "owner", False, "recovery_not_granted"),
        ("staff", "manager", False, "recovery_not_granted"),
        ("manager", "staff", False, "recovery_not_granted"),
        ("owner", "owner", False, "recovery_not_granted"),
        ("manager", "owner", False, "recovery_not_granted"),
        ("manager", "manager", False, "recovery_not_granted"),
        ("staff", "staff", False, "recovery_not_granted"),
    ],
)
def test_administrative_recovery_authorization_matrix_grants_only_owner_to_manager_or_staff(
    actor_class: str,
    target_class: str,
    allowed: bool,
    reason: str,
) -> None:
    is_allowed, evidence = authorize(actor_class=actor_class, target_class=target_class)

    assert is_allowed is allowed
    assert evidence == RecoveryAuthorizationAuditEvidence(
        actor_id="actor-2i",
        target_id="target-2i",
        occurred_at=OCCURRED_AT,
        correlation_id="correlation-2i",
        actor_class=actor_class,
        target_class=target_class,
        outcome="allowed" if allowed else "denied",
        reason=cast(RecoveryAuthorizationReason, reason),
    )


@pytest.mark.parametrize("account_class", ["owner", "manager", "staff"])
def test_self_recovery_is_not_granted_for_any_account_class(account_class: str) -> None:
    is_allowed, evidence = authorize(
        actor_class=account_class,
        target_class=account_class,
        actor_id="same-account",
        target_id="same-account",
    )

    assert not is_allowed
    assert evidence.outcome == "denied"
    assert evidence.reason == "self_recovery_not_granted"


@pytest.mark.parametrize(
    ("actor_class", "target_class"),
    [
        ("unknown", "staff"),
        ("owner", "unknown"),
        ("unknown", "unknown"),
    ],
)
def test_unknown_actor_or_target_class_fails_closed(
    actor_class: str,
    target_class: str,
) -> None:
    is_allowed, evidence = authorize(actor_class=actor_class, target_class=target_class)

    assert not is_allowed
    assert evidence.outcome == "denied"
    assert evidence.reason == "invalid_account_class"
    assert evidence.actor_class == (actor_class if actor_class != "unknown" else "invalid")
    assert evidence.target_class == (target_class if target_class != "unknown" else "invalid")


def test_recovery_authorization_audit_evidence_is_bounded_and_secret_free() -> None:
    sentinel = "credential-like-sensitive-sentinel"

    is_allowed, evidence = authorize(actor_class=sentinel, target_class=sentinel)

    assert not is_allowed
    assert {field.name for field in fields(evidence)} == {
        "actor_id",
        "target_id",
        "occurred_at",
        "correlation_id",
        "actor_class",
        "target_class",
        "outcome",
        "reason",
    }
    assert evidence == RecoveryAuthorizationAuditEvidence(
        actor_id="actor-2i",
        target_id="target-2i",
        occurred_at=OCCURRED_AT,
        correlation_id="correlation-2i",
        actor_class="invalid",
        target_class="invalid",
        outcome="denied",
        reason="invalid_account_class",
    )
    assert sentinel not in repr(evidence)
