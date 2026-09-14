"""Genuine synthetic termination decisions and observed disposition context."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from property_rental.deposit import PostgresDepositService
from property_rental.deposit_disposition import (
    DepositDispositionRule,
    LeaseDepositDispositionContext,
)
from property_rental.lease_enforcement import RecordLeaseWarning, enforcement_request_digest
from property_rental.lease_termination import TerminationBasis
from termination_test_support import approved_test_termination_context


def terminate_for_disposition(
    database_url: str,
    service: PostgresDepositService,
    lease: UUID,
    day: date,
    *,
    voluntary: bool = False,
) -> UUID:
    """Use the protected original command; pet cases carry real general warnings."""
    with psycopg.connect(database_url) as connection:
        warnings: list[UUID] = []
        if not voluntary:
            for number in range(1, 4):
                warning = RecordLeaseWarning(
                    uuid4(),
                    number,
                    day,
                    day,
                    "Synthetic refusal to pay the required approved Pet Deposit",
                    "Synthetic signed Lease required-Pet-Deposit and termination provision",
                    "Synthetic general warning letter delivered and recorded",
                    "Record documented Pet Deposit noncompliance",
                )
                intent = warning.intent()
                row = connection.execute(
                    "SELECT app.lease_enforcement_command(%s,%s,NULL,%s,'WARNING',%s,%s,%s,%s)",
                    (
                        service.property_id,
                        lease,
                        service.actor_id,
                        warning.idempotency_key,
                        enforcement_request_digest(
                            "WARNING", service.property_id, lease, None, intent
                        ),
                        Jsonb(intent),
                        "deposit-disposition-warning",
                    ),
                ).fetchone()
                assert row is not None and isinstance(row[0], dict)
                warnings.append(UUID(row[0]["body"]["data"]["id"]))
        context = approved_test_termination_context(
            TerminationBasis.VOLUNTARY_EARLY if voluntary else TerminationBasis.CUSTOMER_VIOLATION,
            warning_ids=tuple(warnings),
        )
        if not voluntary:
            context = replace(
                context,
                signed_lease_provision=(
                    "Synthetic signed Lease required-Pet-Deposit and termination provision"
                ),
                approved_grounds=(
                    "Approved refusal to pay required Pet Deposit after three warnings"
                ),
                evidence_reference="Synthetic signed decision explicitly authorizes BR-DEP-022",
            )
        row = connection.execute(
            "SELECT version,clock_timestamp() FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert row is not None and type(row[0]) is int and isinstance(row[1], datetime)
        event = uuid4()
        connection.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                service.property_id,
                uuid4(),
                "b" * 64,
                event,
                lease,
                row[0],
                day,
                row[1],
                "BR-LEASE-021" if voluntary else "BR-DEP-022",
                "Approved synthetic voluntary departure"
                if voluntary
                else ("Approved required Pet Deposit noncompliance termination"),
                service.actor_id,
                Jsonb(context.intent()),
            ),
        )
    return event


def disposition_context(database_url: str, deposit: UUID) -> LeaseDepositDispositionContext:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT event.event_id,event.governing_event_reference,"
            "app.deposit_disposition_state_version(deposit.id) FROM app.deposits deposit "
            "JOIN app.leases lease ON lease.id=deposit.lease_id "
            "JOIN app.lease_commands event ON event.lease_id=lease.id "
            "AND event.action='lease.terminate' AND event.occurred_at=lease.terminated_at "
            "WHERE deposit.id=%s",
            (deposit,),
        ).fetchone()
        assert row is not None and isinstance(row[0], UUID) and type(row[2]) is int
        assert row[1] in ("BR-LEASE-021", "BR-DEP-022")
        return LeaseDepositDispositionContext(
            row[0],
            DepositDispositionRule.VOLUNTARY_SECURITY
            if row[1] == "BR-LEASE-021"
            else (DepositDispositionRule.PET_NONCOMPLIANCE),
            row[2],
        )
