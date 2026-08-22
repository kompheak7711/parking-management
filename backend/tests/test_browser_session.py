"""Focused deterministic tests for provider-neutral browser-session lifetime."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from property_rental.browser_session import (
    BrowserSessionAuditEvidence,
    BrowserSessionLifetimeService,
    BrowserSessionState,
)
from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    CapabilityGrant,
    ObjectScope,
    is_authorized,
)


class ControlledClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


class CollectingBrowserSessionAuditSink:
    def __init__(self) -> None:
        self.evidence: list[BrowserSessionAuditEvidence] = []

    def record(self, evidence: BrowserSessionAuditEvidence) -> None:
        self.evidence.append(evidence)


AUTHENTICATED_AT = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)


def session_state(
    *,
    last_activity_at: datetime = AUTHENTICATED_AT,
    revoked_at: datetime | None = None,
) -> BrowserSessionState:
    return BrowserSessionState(
        authenticated_at=AUTHENTICATED_AT,
        last_activity_at=last_activity_at,
        revoked_at=revoked_at,
    )


def service_at(
    instant: datetime,
) -> tuple[BrowserSessionLifetimeService, ControlledClock, CollectingBrowserSessionAuditSink]:
    clock = ControlledClock(instant)
    audit_sink = CollectingBrowserSessionAuditSink()
    return BrowserSessionLifetimeService(clock=clock, audit_sink=audit_sink), clock, audit_sink


def test_session_expires_at_fixed_thirty_minute_inactivity_boundary() -> None:
    service, clock, audit_sink = service_at(AUTHENTICATED_AT + timedelta(minutes=29, seconds=59))

    assert service.evaluate(session_state()).active

    clock.instant = AUTHENTICATED_AT + timedelta(minutes=30)
    decision = service.evaluate(session_state())

    assert not decision.active
    assert decision.reason == "inactive_expired"
    assert audit_sink.evidence[-1] == BrowserSessionAuditEvidence(
        operation="evaluate",
        outcome="denied",
        reason="inactive_expired",
    )


def test_recent_activity_never_extends_fixed_twenty_four_hour_absolute_expiry() -> None:
    service, clock, _ = service_at(AUTHENTICATED_AT + timedelta(hours=23, minutes=59))
    active_session = session_state(
        last_activity_at=AUTHENTICATED_AT + timedelta(hours=23, minutes=45)
    )

    refreshed_session = service.record_activity(active_session)

    assert refreshed_session is not None
    assert refreshed_session.authenticated_at == AUTHENTICATED_AT
    assert refreshed_session.last_activity_at == clock.instant

    clock.instant = AUTHENTICATED_AT + timedelta(hours=24)
    decision = service.evaluate(refreshed_session)

    assert not decision.active
    assert decision.reason == "absolute_expired"


def test_activity_updates_only_last_activity_for_an_active_session() -> None:
    service, clock, audit_sink = service_at(AUTHENTICATED_AT + timedelta(minutes=10))

    updated_session = service.record_activity(session_state())

    assert updated_session == session_state(last_activity_at=clock.instant)
    assert audit_sink.evidence == [
        BrowserSessionAuditEvidence(operation="activity", outcome="recorded", reason="active")
    ]


def test_expired_session_activity_is_rejected_without_timestamp_change() -> None:
    service, _, audit_sink = service_at(AUTHENTICATED_AT + timedelta(minutes=30))

    assert service.record_activity(session_state()) is None
    assert audit_sink.evidence == [
        BrowserSessionAuditEvidence(
            operation="activity",
            outcome="denied",
            reason="inactive_expired",
        )
    ]


def test_explicit_revocation_fails_closed_for_evaluation_and_activity() -> None:
    service, clock, audit_sink = service_at(AUTHENTICATED_AT + timedelta(minutes=5))

    revoked_session = service.revoke(session_state())

    assert revoked_session.revoked_at == clock.instant
    assert not service.evaluate(revoked_session).active
    assert service.record_activity(revoked_session) is None
    assert [evidence.reason for evidence in audit_sink.evidence] == [
        "revoked",
        "revoked",
        "revoked",
    ]


def test_logout_revocation_cannot_be_bypassed_by_fresh_activity() -> None:
    service, clock, _ = service_at(AUTHENTICATED_AT + timedelta(minutes=5))
    logged_out_session = service.revoke(session_state())

    clock.instant += timedelta(seconds=1)

    assert service.record_activity(logged_out_session) is None
    decision = service.evaluate(logged_out_session)
    assert not decision.active
    assert decision.reason == "revoked"


@pytest.mark.parametrize(
    ("ordinary_capability", "high_value_capability"),
    [
        ("invoices.edit", "late_payment.final_decision"),
        ("late_payment.final_decision", "late_payment.charge_correction"),
        ("payments.read", "receipts.reprint"),
        ("deposits.manage", "pet_deposits.active_lease_refund_qualify"),
        ("leases.warn", "rent_nonpayment.case_manage"),
        ("customer_ledger.read", "customer_ledger.source_mutate"),
    ],
)
def test_production_authorizer_keeps_session_state_and_high_value_capabilities_independent(
    ordinary_capability: str,
    high_value_capability: str,
) -> None:
    assert {field.name for field in fields(BrowserSessionState)} == {
        "authenticated_at",
        "last_activity_at",
        "revoked_at",
    }
    object_scope = ObjectScope(object_type="workflow", object_id="workflow-1")
    actor = AuthenticatedActor(
        actor_id="actor-1",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability=ordinary_capability,
                    property_ids=frozenset({"property-1"}),
                    object_scopes=frozenset({object_scope}),
                )
            }
        ),
    )

    assert is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ordinary_capability,
            property_id="property-1",
            object_scope=object_scope,
        ),
    )
    assert not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=high_value_capability,
            property_id="property-1",
            object_scope=object_scope,
        ),
    )
    assert not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ordinary_capability,
            property_id="property-2",
            object_scope=object_scope,
        ),
    )
    assert not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ordinary_capability,
            property_id="property-1",
            object_scope=ObjectScope(
                object_type="workflow",
                object_id="workflow-2",
            ),
        ),
    )


@pytest.mark.parametrize(
    "state",
    [
        BrowserSessionState(
            authenticated_at=datetime(2026, 8, 18, 0, 0),
            last_activity_at=datetime(2026, 8, 18, 0, 1),
        ),
        session_state(last_activity_at=AUTHENTICATED_AT - timedelta(seconds=1)),
        session_state(last_activity_at=AUTHENTICATED_AT + timedelta(seconds=1)),
    ],
)
def test_invalid_or_future_session_timestamps_fail_closed(state: BrowserSessionState) -> None:
    service, _, audit_sink = service_at(AUTHENTICATED_AT)

    decision = service.evaluate(state)

    assert not decision.active
    assert decision.reason == "invalid_timestamps"
    assert audit_sink.evidence == [
        BrowserSessionAuditEvidence(
            operation="evaluate",
            outcome="denied",
            reason="invalid_timestamps",
        )
    ]


def test_session_audit_evidence_is_fixed_bounded_and_secret_free() -> None:
    service, _, audit_sink = service_at(AUTHENTICATED_AT + timedelta(minutes=1))

    service.evaluate(session_state())

    assert {field.name for field in fields(audit_sink.evidence[0])} == {
        "operation",
        "outcome",
        "reason",
    }
    assert audit_sink.evidence == [
        BrowserSessionAuditEvidence(operation="evaluate", outcome="allowed", reason="active")
    ]
