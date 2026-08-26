"""Domain tests for the bounded V1-034 Lease lifecycle service contract."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseAuthorizationError,
    LeaseDraftCommand,
    LeaseSignCommand,
    LeaseStatus,
    PostgresLeaseService,
    lease_request_digest,
)


def draft_command() -> LeaseDraftCommand:
    return LeaseDraftCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=uuid4(),
        unit_id=uuid4(),
        primary_tenant_id=uuid4(),
        primary_signer_id=uuid4(),
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent_usd_cents=80_000,
        predecessor_lease_id=None,
        reason="Authorized Lease draft",
        authorization_reference=LEASE_DRAFT_CAPABILITY,
    )


def test_lease_status_vocabulary_is_closed_and_has_no_month_to_month_state() -> None:
    assert {status.value for status in LeaseStatus} == {
        "DRAFTED",
        "SIGNED",
        "CANCELLED",
        "TERMINATED",
    }


def test_request_digest_is_stable_and_binds_every_command_input() -> None:
    command = draft_command()

    first = lease_request_digest("lease.draft", command)
    second = lease_request_digest("lease.draft", command)
    changed = lease_request_digest("lease.draft", replace(command, monthly_rent_usd_cents=81_000))

    assert first == second
    assert len(first) == 64
    assert changed != first
    with pytest.raises(ValueError, match="action"):
        lease_request_digest("reservation.create", command)


def test_draft_rejects_partial_or_reversed_contractual_periods() -> None:
    command = draft_command()

    with pytest.raises(ValueError, match="supplied together"):
        replace(command, end_date=None)
    with pytest.raises(ValueError, match="later"):
        replace(command, end_date=command.start_date)
    with pytest.raises(ValueError, match="positive"):
        replace(command, monthly_rent_usd_cents=0)


def test_service_rejects_wrong_actor_scope_capability_and_authorization_evidence() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    command = LeaseSignCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=uuid4(),
        expected_version=1,
        signed_at=datetime(2027, 1, 1, tzinfo=UTC),
        reason="All Lease Signers completed signing",
        authorization_reference=LEASE_SIGN_CAPABILITY,
    )
    service = PostgresLeaseService(
        "postgresql://must-not-be-used", property_id=property_id, actor_id=actor_id
    )
    scope = frozenset({str(property_id)})

    with pytest.raises(LeaseAuthorizationError, match="does not match"):
        service.sign(
            command,
            actor=AuthenticatedActor(
                actor_id=str(uuid4()),
                capability_grants=frozenset({CapabilityGrant(LEASE_SIGN_CAPABILITY, scope)}),
            ),
        )
    with pytest.raises(LeaseAuthorizationError, match="not authorized"):
        service.sign(
            command,
            actor=AuthenticatedActor(actor_id=str(actor_id), capability_grants=frozenset()),
        )
    with pytest.raises(LeaseAuthorizationError, match="not authoritative"):
        service.sign(
            replace(command, authorization_reference="untrusted.claim"),
            actor=AuthenticatedActor(
                actor_id=str(actor_id),
                capability_grants=frozenset({CapabilityGrant(LEASE_SIGN_CAPABILITY, scope)}),
            ),
        )
