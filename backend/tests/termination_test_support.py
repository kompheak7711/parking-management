"""Explicit synthetic signed authority for existing termination integration fixtures."""

from datetime import date, datetime
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from property_rental.lease_enforcement import RecordLeaseWarning, enforcement_request_digest
from property_rental.lease_termination import TerminationBasis, TerminationContext


def approved_test_termination_context(
    basis: TerminationBasis = TerminationBasis.SIGNED_LEASE_OTHER,
    *,
    warning_ids: tuple[UUID, ...] = (),
) -> TerminationContext:
    return TerminationContext(
        basis=basis,
        signed_lease_provision="Synthetic signed Lease termination provision",
        approved_grounds="Explicit management-approved synthetic departure",
        management_authorization_reference="Synthetic management decision TERM-001",
        evidence_reference="Signed synthetic termination record TERM-001",
        notice_required=False,
        notice_exception_reason="Signed surrender terms expressly approve this notice exception",
        warning_ids=warning_ids,
    )


def terminate_test_lease(
    connection: Connection[tuple[object, ...]],
    *,
    property_id: UUID,
    actor_id: UUID,
    lease_id: UUID,
    governing: str,
    reason: str,
    basis: TerminationBasis,
    actual_date: date | None = None,
    expected_version: int | None = None,
    occurred_at: datetime | None = None,
    request_digest: str = "a" * 64,
    legacy: bool = False,
) -> None:
    """Create real prerequisite sources; legacy mode is only for pre54 upgrade fixtures."""
    if actual_date is None:
        day = connection.execute("SELECT current_date").fetchone()
        assert day is not None and type(day[0]) is date
        actual_date = day[0]
    if legacy:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() in (
            ("20260911_52",),
            ("20260914_53",),
        )
    warning_ids: list[UUID] = []
    if not legacy and basis is TerminationBasis.CUSTOMER_VIOLATION:
        for sequence in range(1, 4):
            warning = RecordLeaseWarning(
                uuid4(),
                sequence,
                actual_date,
                actual_date,
                "Synthetic documented signed-Lease violation",
                "Synthetic signed Lease termination provision",
                "Synthetic written warning delivered to the Customer",
                "Record the actual synthetic general warning prerequisite",
            )
            intent = warning.intent()
            row = connection.execute(
                "SELECT app.lease_enforcement_command(%s,%s,NULL,%s,'WARNING',%s,%s,%s,%s)",
                (
                    property_id,
                    lease_id,
                    actor_id,
                    warning.idempotency_key,
                    enforcement_request_digest("WARNING", property_id, lease_id, None, intent),
                    Jsonb(intent),
                    "termination-test-warning",
                ),
            ).fetchone()
            assert row is not None and isinstance(row[0], dict)
            warning_ids.append(UUID(row[0]["body"]["data"]["id"]))
    row = connection.execute(
        "SELECT version,statement_timestamp() FROM app.leases WHERE id=%s", (lease_id,)
    ).fetchone()
    assert row is not None and isinstance(row[1], datetime)
    parameters: tuple[object, ...] = (
        property_id,
        uuid4(),
        request_digest,
        uuid4(),
        lease_id,
        expected_version if expected_version is not None else int(str(row[0])),
        actual_date,
        occurred_at or row[1],
        governing,
        reason,
        actor_id,
    )
    if legacy:
        connection.execute(
            "SELECT app.terminate_lease(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", parameters
        )
    else:
        context = approved_test_termination_context(basis, warning_ids=tuple(warning_ids))
        connection.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (*parameters, Jsonb(context.intent())),
        )
