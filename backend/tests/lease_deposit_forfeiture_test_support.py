"""Lease Deposit forfeitures in tests after V1-056 slice 6 (BR-AUTH-010).

Since migration 20261018_83 a Lease Deposit forfeiture is a draft that takes effect only when a
financial.approve holder confirms it, and the financial role can no longer execute the one-call
disposition and reversal functions (owner answers to Q-2026-10-04-12 and Q-2026-10-04-13).

- ``forfeit_through_draft`` uses the real path: the person records the draft under
  deposits.dispose and, holding financial.approve, confirms it. A repeated call with the same
  key and disposition id replays both steps.
- ``reverse_through_draft`` (sub-slice 6b) records the forfeiture reversal draft under
  deposits.correct and confirms it as the same financial.approve holder.
- ``record_disposition_as_owner`` and ``reverse_disposition_as_owner`` call the earlier one-call
  database functions as the database owner, with the same parameters and error mapping the
  service used. They are only for tests where the disposition or reversal is setup for another
  subject, tests of the database function's own guards that the draft path cannot reach
  (partial amount, explicit stale context, raw replay), and tests of earlier migration
  revisions.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from property_rental.deposit import (
    DEPOSIT_CORRECT_CAPABILITY,
    DEPOSIT_DISPOSE_CAPABILITY,
    DepositSnapshot,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    _snapshot,
    deposit_request_digest,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_deposit_forfeiture import (
    FINANCIAL_APPROVE_CAPABILITY,
    LeaseDepositForfeitureService,
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
)


def owner_database_url(database_url: str) -> str:
    """The same database and connection options, signed in as the migration owner."""
    migration = os.environ.get("MIGRATION_DATABASE_URL")
    if migration is None:
        raise RuntimeError("MIGRATION_DATABASE_URL is required for owner test setup")
    owner = conninfo_to_dict(migration.replace("postgresql+psycopg://", "postgresql://", 1))
    return make_conninfo(database_url, user=owner["user"], password=owner["password"])


def _as_owner(service: PostgresDepositService) -> PostgresDepositService:
    return replace(
        service, financial_database_url=owner_database_url(service.financial_database_url)
    )


def record_disposition_as_owner(
    service: PostgresDepositService,
    command: RecordDepositDispositionCommand,
    *,
    actor: AuthenticatedActor,
) -> DepositSnapshot:
    """The one-call Lease disposition the service sent before slice 6, run as the owner."""
    service._authorize(actor, DEPOSIT_DISPOSE_CAPABILITY, command.authorization_reference)
    parameters: tuple[object, ...] = (
        service.property_id,
        service.actor_id,
        command.idempotency_key,
        deposit_request_digest("deposit.disposition.record", command),
        command.disposition_id,
        command.deposit_id,
        command.governing_lease_id,
        command.amount_usd_cents,
        command.effective_date,
        command.reason,
        command.authorization_reference,
    )
    if command.context is None:
        return _as_owner(service)._execute(
            "SELECT app.record_lease_deposit_disposition(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            parameters,
        )
    return _as_owner(service)._execute(
        "SELECT app.record_lease_deposit_disposition_with_context("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            *parameters,
            command.context.termination_event_id,
            command.context.governing_rule,
            command.context.expected_state_version,
        ),
    )


def reverse_disposition_as_owner(
    service: PostgresDepositService,
    command: ReverseDepositDispositionCommand,
    *,
    actor: AuthenticatedActor,
) -> DepositSnapshot:
    """The one-call Lease disposition reversal the service sent before slice 6, as the owner."""
    service._authorize(actor, DEPOSIT_CORRECT_CAPABILITY, command.authorization_reference)
    return _as_owner(service)._execute(
        "SELECT app.reverse_deposit_disposition_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            service.property_id,
            service.actor_id,
            command.idempotency_key,
            deposit_request_digest("deposit.disposition.reverse", command),
            command.reversal_id,
            command.disposition_id,
            command.reason,
            command.evidence_reference,
            command.authorization_reference,
        ),
    )


def _approver(service: PostgresDepositService, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(service.property_id)})
    return AuthenticatedActor(
        str(service.actor_id),
        frozenset(
            CapabilityGrant(capability, scope)
            for capability in (*capabilities, FINANCIAL_APPROVE_CAPABILITY)
        ),
    )


def reverse_through_draft(
    service: PostgresDepositService,
    disposition_id: UUID,
    *,
    reversal_id: UUID | None = None,
    idempotency_key: UUID | None = None,
    reason: str = "Approved forfeiture correction",
    evidence_reference: str = "Reviewed correction evidence",
) -> DepositSnapshot:
    """Record the forfeiture reversal draft and confirm it as the same financial.approve holder."""
    person = _approver(service, DEPOSIT_CORRECT_CAPABILITY)
    forfeitures = LeaseDepositForfeitureService(service.financial_database_url)
    draft = forfeitures.record_reversal(
        service.property_id,
        RecordLeaseDepositReversalCommand(
            idempotency_key or uuid4(),
            disposition_id,
            reversal_id or uuid4(),
            reason,
            evidence_reference,
        ),
        actor=person,
    )
    confirmed = forfeitures.confirm_reversal(
        service.property_id, disposition_id, UUID(str(draft["draft_id"])), actor=person
    )
    return _snapshot((cast(dict[str, object], confirmed["deposit"]),))


def forfeit_through_draft(
    service: PostgresDepositService,
    deposit_id: UUID,
    *,
    disposition_id: UUID | None = None,
    idempotency_key: UUID | None = None,
    reason: str = "Approved Lease Deposit forfeiture",
) -> DepositSnapshot:
    """Record the forfeiture draft and confirm it as the same financial.approve holder."""
    person = _approver(service, DEPOSIT_DISPOSE_CAPABILITY)
    forfeitures = LeaseDepositForfeitureService(service.financial_database_url)
    draft = forfeitures.record(
        service.property_id,
        RecordLeaseDepositForfeitureCommand(
            idempotency_key or uuid4(), deposit_id, disposition_id or uuid4(), reason
        ),
        actor=person,
    )
    confirmed = forfeitures.confirm(
        service.property_id, deposit_id, UUID(str(draft["draft_id"])), actor=person
    )
    return _snapshot((cast(dict[str, object], confirmed["deposit"]),))
