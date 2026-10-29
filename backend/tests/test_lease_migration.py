"""Real PostgreSQL coverage for V1-033 Lease persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error

from unit_type_support import seeded_unit_type


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Apply all migrations to the disposable PostgreSQL database."""
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    """Provide an isolated migration-owner transaction."""
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def setup_sources(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    """Create one actor, Property, Unit, primary tenant, and additional Customer."""
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s, %s, 'Lease Tester', 'Lease Tester', 'active', 'optional', 'test')
        """,
        (actor_id, f"lease-{actor_id}"),
    )
    existing_property = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing_property is None:
        property_id = uuid4()
        connection.execute(
            "INSERT INTO app.properties(id, name, created_by, updated_by) "
            "VALUES (%s, 'Lease Test Property', %s, %s)",
            (property_id, actor_id, actor_id),
        )
    else:
        property_id = UUID(str(existing_property[0]))
    unit_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.units(
            id, property_id, unit_number, floor, unit_type, status, created_by, updated_by
        ) VALUES (%s, %s, %s, '1', %s, 'VACANT', %s, %s)
        """,
        (
            unit_id,
            property_id,
            f"LEASE-{unit_id.hex[:12]}",
            seeded_unit_type(connection, property_id),
            actor_id,
            actor_id,
        ),
    )
    primary_tenant_id = uuid4()
    occupant_id = uuid4()
    for customer_id, legal_name in (
        (primary_tenant_id, "Primary Lease Customer"),
        (occupant_id, "Non-signing Occupant"),
    ):
        connection.execute(
            "INSERT INTO app.customers(id, legal_name, created_by, updated_by) "
            "VALUES (%s,%s,%s,%s)",
            (customer_id, legal_name, actor_id, actor_id),
        )
    return actor_id, property_id, unit_id, primary_tenant_id, occupant_id


def create_draft(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    unit_id: UUID,
    primary_tenant_id: UUID,
    lease_id: UUID | None = None,
    start_date: date = date(2027, 1, 1),
    end_date: date = date(2027, 12, 31),
    signed: bool = True,
    predecessor_lease_id: UUID | None = None,
) -> UUID:
    """Insert a canonical draft and its Primary Tenant signer."""
    stored_lease_id = lease_id or uuid4()
    connection.execute(
        """
        INSERT INTO app.leases(
            id, unit_id, primary_tenant_id, start_date, end_date,
            monthly_rent_usd_cents, predecessor_lease_id, created_by, updated_by
        ) VALUES (%s,%s,%s,%s,%s,80000,%s,%s,%s)
        """,
        (
            stored_lease_id,
            unit_id,
            primary_tenant_id,
            start_date,
            end_date,
            predecessor_lease_id,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.lease_signers(id, lease_id, customer_id, signed_at, added_by)
        VALUES (%s,%s,%s,CASE WHEN %s THEN statement_timestamp() ELSE NULL END,%s)
        """,
        (uuid4(), stored_lease_id, primary_tenant_id, signed, actor_id),
    )
    return stored_lease_id


def sign_lease(connection: Connection[tuple[object, ...]], lease_id: UUID, actor_id: UUID) -> None:
    """Move one complete draft into its signed persistence shape."""
    connection.execute(
        """
        UPDATE app.leases SET status='SIGNED', signed_at=statement_timestamp(),
            version=version+1, updated_at=statement_timestamp(), updated_by=%s
        WHERE id=%s
        """,
        (actor_id, lease_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_lease_requires_signed_primary_tenant_and_preserves_revisions(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, _ = setup_sources(connection)
    incomplete_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        signed=False,
    )
    connection.execute(
        """
        UPDATE app.leases SET status='SIGNED', signed_at=statement_timestamp(),
            version=2, updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
        """,
        (actor_id, incomplete_id),
    )
    with pytest.raises(Error) as missing_signature:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert missing_signature.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _, unit_id, tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    assert connection.execute(
        "SELECT status, version, signed_at IS NOT NULL FROM app.leases WHERE id=%s",
        (lease_id,),
    ).fetchone() == ("SIGNED", 2, True)
    assert connection.execute(
        "SELECT version, status FROM app.lease_revisions WHERE lease_id=%s ORDER BY version",
        (lease_id,),
    ).fetchall() == [(1, "DRAFTED"), (2, "SIGNED")]


def test_only_legal_lifecycle_transitions_are_persisted(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, _ = setup_sources(connection)
    cancelled_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    with pytest.raises(Error) as draft_termination:
        with connection.transaction():
            connection.execute(
                """
                UPDATE app.leases SET status='TERMINATED', signed_at=statement_timestamp(),
                    terminated_at=statement_timestamp(), actual_termination_date=%s,
                    termination_reason='Unsupported direct termination', version=2,
                    updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
                """,
                (date(2027, 6, 30), actor_id, cancelled_id),
            )
    assert draft_termination.value.sqlstate == "55000"
    connection.execute(
        "UPDATE app.leases SET status='CANCELLED', version=2, "
        "updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
        (actor_id, cancelled_id),
    )
    assert connection.execute(
        "SELECT status, version FROM app.leases WHERE id=%s", (cancelled_id,)
    ).fetchone() == ("CANCELLED", 2)
    with pytest.raises(Error) as cancelled_terminal:
        with connection.transaction():
            connection.execute(
                "UPDATE app.leases SET status='DRAFTED', version=3, "
                "updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
                (actor_id, cancelled_id),
            )
    assert cancelled_terminal.value.sqlstate == "55000"

    second_unit_id = uuid4()
    property_row = connection.execute(
        "SELECT property_id FROM app.units WHERE id=%s", (unit_id,)
    ).fetchone()
    assert property_row is not None
    property_id = property_row[0]
    connection.execute(
        """
        INSERT INTO app.units(
            id, property_id, unit_number, floor, unit_type, status, created_by, updated_by
        ) VALUES (%s,%s,%s,'1',%s,'VACANT',%s,%s)
        """,
        (
            second_unit_id,
            property_id,
            f"LEASE-{second_unit_id.hex[:12]}",
            seeded_unit_type(connection, property_id),
            actor_id,
            actor_id,
        ),
    )
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=second_unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    with pytest.raises(Error) as signed_to_draft:
        with connection.transaction():
            connection.execute(
                """
                UPDATE app.leases SET status='DRAFTED', signed_at=NULL, version=3,
                    updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
                """,
                (actor_id, lease_id),
            )
    assert signed_to_draft.value.sqlstate == "55000"
    with pytest.raises(Error) as cancellation:
        with connection.transaction():
            connection.execute(
                "UPDATE app.leases SET status='CANCELLED', version=3, "
                "updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
                (actor_id, lease_id),
            )
    assert cancellation.value.sqlstate == "55000"
    connection.execute(
        """
        UPDATE app.leases SET status='TERMINATED', terminated_at=statement_timestamp(),
            actual_termination_date=%s, termination_reason='Authorized termination',
            version=3, updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
        """,
        (date(2027, 6, 30), actor_id, lease_id),
    )
    assert connection.execute(
        "SELECT status, actual_termination_date, version FROM app.leases WHERE id=%s",
        (lease_id,),
    ).fetchone() == ("TERMINATED", date(2027, 6, 30), 3)
    with pytest.raises(Error) as terminated_terminal:
        with connection.transaction():
            connection.execute(
                "UPDATE app.leases SET termination_reason='Rewritten', version=4, "
                "updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
                (actor_id, lease_id),
            )
    assert terminated_terminal.value.sqlstate == "55000"

    elapsed_unit_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.units(
            id, property_id, unit_number, floor, unit_type, status, created_by, updated_by
        ) VALUES (%s,%s,%s,'1',%s,'VACANT',%s,%s)
        """,
        (
            elapsed_unit_id,
            property_id,
            f"LEASE-{elapsed_unit_id.hex[:12]}",
            seeded_unit_type(connection, property_id),
            actor_id,
            actor_id,
        ),
    )
    elapsed_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=elapsed_unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
    )
    sign_lease(connection, elapsed_id, actor_id)
    assert connection.execute(
        "SELECT status, version FROM app.leases WHERE id=%s AND end_date < CURRENT_DATE",
        (elapsed_id,),
    ).fetchone() == ("SIGNED", 2)
    assert connection.execute(
        "SELECT count(*) FROM app.leases WHERE unit_id=%s", (elapsed_unit_id,)
    ).fetchone() == (1,)


def test_signer_history_is_append_preserved_after_signing(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, occupant_id = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    second_actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts(
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s,%s,'Second Lease Actor','Second Lease Actor','active','optional','test')
        """,
        (second_actor_id, f"lease-second-{second_actor_id}"),
    )
    additional_signer_id = uuid4()
    connection.execute(
        "INSERT INTO app.lease_signers(id, lease_id, customer_id, signed_at, added_by) "
        "VALUES (%s,%s,%s,NULL,%s)",
        (additional_signer_id, lease_id, occupant_id, actor_id),
    )
    connection.execute(
        "SELECT app.sign_draft_lease_signer(%s, statement_timestamp(), %s)",
        (additional_signer_id, second_actor_id),
    )
    removable_customer_id = uuid4()
    connection.execute(
        "INSERT INTO app.customers(id, legal_name, created_by, updated_by) "
        "VALUES (%s,'Removed Draft Signer',%s,%s)",
        (removable_customer_id, actor_id, actor_id),
    )
    removable_signer_id = uuid4()
    connection.execute(
        "INSERT INTO app.lease_signers(id, lease_id, customer_id, signed_at, added_by) "
        "VALUES (%s,%s,%s,NULL,%s)",
        (removable_signer_id, lease_id, removable_customer_id, actor_id),
    )
    connection.execute(
        "SELECT app.remove_draft_lease_signer(%s, %s)",
        (removable_signer_id, second_actor_id),
    )
    assert connection.execute(
        """
        SELECT operation, actor_id FROM app.lease_signer_history
        WHERE signer_id IN (%s,%s) AND operation IN ('SIGNED','REMOVED')
        ORDER BY operation
        """,
        (additional_signer_id, removable_signer_id),
    ).fetchall() == [("REMOVED", second_actor_id), ("SIGNED", second_actor_id)]
    sign_lease(connection, lease_id, actor_id)
    with pytest.raises(Error) as signer_deletion:
        with connection.transaction():
            connection.execute(
                "SELECT app.remove_draft_lease_signer(%s, %s)",
                (additional_signer_id, second_actor_id),
            )
    assert signer_deletion.value.sqlstate == "55000"


def test_occupancy_date_order_and_nonfinancial_shape_are_enforced(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, occupant_id = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    with pytest.raises(Error) as reversed_period:
        connection.execute(
            """
            INSERT INTO app.occupancies(
                id, lease_id, customer_id, move_in_date, move_out_date,
                created_by, updated_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                uuid4(),
                lease_id,
                occupant_id,
                date(2027, 2, 1),
                date(2027, 1, 31),
                actor_id,
                actor_id,
            ),
        )
    assert reversed_period.value.sqlstate == "23514"
    connection.rollback()

    columns = {
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='app' AND table_name='occupancies'"
        ).fetchall()
    }
    assert not columns.intersection(
        {"balance", "debt", "responsibility_percentage", "responsibility_usd_cents"}
    )


def test_signed_periods_are_exclusive_and_successor_lineage_is_constrained(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, _ = setup_sources(connection)
    mutable_predecessor_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
    )
    with pytest.raises(Error) as mutable_predecessor:
        with connection.transaction():
            create_draft(
                connection,
                actor_id=actor_id,
                unit_id=unit_id,
                primary_tenant_id=tenant_id,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 12, 31),
                predecessor_lease_id=mutable_predecessor_id,
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mutable_predecessor.value.sqlstate == "23514"

    first_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 6, 30),
    )
    sign_lease(connection, first_id, actor_id)
    connection.execute(
        """
        UPDATE app.leases SET status='TERMINATED', terminated_at=statement_timestamp(),
            actual_termination_date=%s, termination_reason='Approved early termination',
            version=3, updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
        """,
        (date(2027, 6, 30), actor_id, first_id),
    )
    successor_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 7, 1),
        end_date=date(2027, 12, 31),
    )
    sign_lease(connection, successor_id, actor_id)
    assert connection.execute(
        "SELECT status FROM app.leases WHERE id=%s", (successor_id,)
    ).fetchone() == ("SIGNED",)
    renewal_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2028, 1, 1),
        end_date=date(2028, 12, 31),
        predecessor_lease_id=successor_id,
    )
    sign_lease(connection, renewal_id, actor_id)
    assert connection.execute(
        "SELECT predecessor_lease_id, status FROM app.leases WHERE id=%s", (renewal_id,)
    ).fetchone() == (successor_id, "SIGNED")

    overlapping_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 6, 30),
        end_date=date(2027, 7, 15),
    )
    with pytest.raises(Error) as overlap:
        sign_lease(connection, overlapping_id, actor_id)
    assert overlap.value.sqlstate == "23P01"
    connection.rollback()


def test_signers_and_occupants_remain_distinct_with_complete_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, occupant_id = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    occupancy_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.occupancies(
            id, lease_id, customer_id, move_in_date, created_by, updated_by
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (occupancy_id, lease_id, occupant_id, date(2027, 1, 2), actor_id, actor_id),
    )
    connection.execute(
        """
        UPDATE app.occupancies SET move_out_date=%s, version=2,
            updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
        """,
        (date(2027, 10, 1), actor_id, occupancy_id),
    )
    connection.execute(
        """
        UPDATE app.occupancies SET move_in_date=%s, move_out_date=%s, version=3,
            updated_at=statement_timestamp(), updated_by=%s WHERE id=%s
        """,
        (date(2027, 1, 3), date(2027, 9, 30), actor_id, occupancy_id),
    )
    assert connection.execute(
        "SELECT customer_id FROM app.lease_signers WHERE lease_id=%s", (lease_id,)
    ).fetchall() == [(tenant_id,)]
    assert connection.execute(
        "SELECT customer_id, move_in_date, move_out_date FROM app.occupancies WHERE id=%s",
        (occupancy_id,),
    ).fetchone() == (occupant_id, date(2027, 1, 3), date(2027, 9, 30))
    assert connection.execute(
        "SELECT version, move_out_date FROM app.occupancy_revisions "
        "WHERE occupancy_id=%s ORDER BY version",
        (occupancy_id,),
    ).fetchall() == [(1, None), (2, date(2027, 10, 1)), (3, date(2027, 9, 30))]


def test_history_cannot_be_deleted_or_rewritten(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    with pytest.raises(Error) as deletion:
        with connection.transaction():
            connection.execute("DELETE FROM app.leases WHERE id=%s", (lease_id,))
    assert deletion.value.sqlstate == "55000"
    with pytest.raises(Error) as revision_rewrite:
        with connection.transaction():
            connection.execute(
                "UPDATE app.lease_revisions SET status='CANCELLED' WHERE lease_id=%s AND version=1",
                (lease_id,),
            )
    assert revision_rewrite.value.sqlstate == "55000"
    with pytest.raises(Error) as revision_deletion:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.lease_signer_history WHERE lease_id=%s", (lease_id,)
            )
    assert revision_deletion.value.sqlstate == "55000"


@pytest.mark.parametrize("concurrency_round", range(3))
def test_concurrent_signing_allows_only_one_overlapping_lease(
    migrated_database_url: str, concurrency_round: int
) -> None:
    del concurrency_round
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, _, unit_id, tenant_id, _ = setup_sources(setup)
        lease_ids = [
            create_draft(setup, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id)
            for _ in range(2)
        ]
        setup.commit()
    barrier = Barrier(2)

    def attempt(lease_id: UUID) -> str:
        with psycopg.connect(migrated_database_url) as competing:
            barrier.wait(timeout=5)
            try:
                sign_lease(competing, lease_id, actor_id)
                competing.commit()
                return "success"
            except Error as error:
                competing.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(attempt, lease_ids))
    assert outcomes == ["23P01", "success"]


def test_nonbilling_lease_event_term_and_pet_stores_are_append_only(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    notice_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.termination_notices(
            id, lease_id, notice_date, intended_termination_date, notice_text,
            governing_lease_provision, occurred_at, actor_id
        ) VALUES (%s,%s,%s,%s,'Signed notice terms','Lease clause 10',clock_timestamp(),%s)
        """,
        (notice_id, lease_id, date(2027, 10, 1), date(2027, 12, 31), actor_id),
    )
    connection.execute(
        """
        INSERT INTO app.lease_violation_warnings(
            id, lease_id, warning_sequence, violation_date, warning_date,
            violation_description, lease_provision, communication_record,
            occurred_at, actor_id
        ) VALUES (%s,%s,1,%s,%s,'Documented violation','Lease clause 12',
                  'Delivered letter',clock_timestamp(),%s)
        """,
        (uuid4(), lease_id, date(2027, 4, 1), date(2027, 4, 2), actor_id),
    )
    pet_approval_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.lease_pet_approvals(
            id, lease_id, approved_date, deposit_required_by_signed_terms,
            pet_description, approved_at, approved_by
        ) VALUES (%s,%s,%s,true,'One approved cat',clock_timestamp(),%s)
        """,
        (pet_approval_id, lease_id, date(2027, 1, 1), actor_id),
    )
    service_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.property_services(
            id, property_id, service_code, display_name, configured_by,
            created_by, updated_by
        ) VALUES (%s,%s,%s,'Parking Service',%s,%s,%s)
        """,
        (service_id, property_id, f"parking-{service_id.hex[:8]}", actor_id, actor_id, actor_id),
    )
    approval_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.property_service_approval_periods(
            id, property_service_id, effective_from, effective_through,
            approval_reference, approved_at, approved_by, reason
        ) VALUES (%s,%s,%s,%s,'owner-approval',clock_timestamp(),%s,'Approved terms')
        """,
        (approval_id, service_id, date(2027, 1, 1), None, actor_id),
    )
    draft_lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    draft_term_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.lease_service_terms(
            id, lease_id, property_service_id, applicable_from, applicable_through,
            service_approval_period_id, terms_reference, recorded_at, recorded_by
        ) VALUES (%s,%s,%s,%s,%s,%s,'draft-term',clock_timestamp(),%s)
        """,
        (
            draft_term_id,
            draft_lease_id,
            service_id,
            date(2027, 1, 1),
            date(2027, 12, 31),
            approval_id,
            actor_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT terms_reference FROM app.lease_service_terms WHERE id=%s",
        (draft_term_id,),
    ).fetchone() == ("draft-term",)
    departure_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.lease_service_terms(
            id, lease_id, property_service_id, applicable_from, applicable_through,
            service_approval_period_id, terms_reference, recorded_at, recorded_by
        ) VALUES (%s,%s,%s,%s,%s,%s,'signed-lease-service-term',clock_timestamp(),%s)
        """,
        (
            uuid4(),
            lease_id,
            service_id,
            date(2027, 1, 1),
            date(2027, 12, 31),
            approval_id,
            actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.lease_pet_departures(
            id, pet_approval_id, lease_id, permanently_left_date,
            reason, occurred_at, actor_id
        ) VALUES (%s,%s,%s,%s,'Pet permanently left',clock_timestamp(),%s)
        """,
        (departure_id, pet_approval_id, lease_id, date(2027, 8, 1), actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as invalid_approval_closure:
        with connection.transaction():
            connection.execute(
                "UPDATE app.property_service_approval_periods SET effective_through=%s WHERE id=%s",
                (date(2027, 6, 30), approval_id),
            )
    assert invalid_approval_closure.value.sqlstate == "23514"

    connection.execute("ALTER TABLE app.deposits DISABLE TRIGGER deposits_validate_source")
    connection.execute(
        "ALTER TABLE app.deposits DROP CONSTRAINT deposits_type_check, "
        "DROP CONSTRAINT deposits_source_shape, DROP CONSTRAINT deposits_pet_approval_fkey"
    )
    connection.execute("DROP INDEX app.deposits_pet_lease_unique")
    connection.execute("DROP INDEX app.deposits_pet_approval_unique")
    matching_pet_deposit_id = uuid4()
    mismatched_pet_deposit_id = uuid4()
    for deposit_id, approval_reference in (
        (matching_pet_deposit_id, pet_approval_id),
        (mismatched_pet_deposit_id, uuid4()),
    ):
        connection.execute(
            """
            INSERT INTO app.deposits(
                id, deposit_type, customer_id, reservation_id, lease_id,
                pet_approval_id, required_usd_cents, required_effective_date,
                created_by, updated_by
            ) VALUES (%s,'PET',%s,NULL,%s,%s,10000,%s,%s,%s)
            """,
            (
                deposit_id,
                tenant_id,
                lease_id,
                approval_reference,
                date(2027, 1, 1),
                actor_id,
                actor_id,
            ),
        )
    with pytest.raises(Error) as mismatched_pet_review:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO app.pet_deposit_refund_reviews(
                    id, pet_departure_id, pet_deposit_id,
                    obligations_reviewed_usd_cents, review_findings,
                    all_pet_obligations_resolved, resolution_reference, reason,
                    reviewed_at, reviewed_by, authorization_reference
                ) VALUES (%s,%s,%s,0,'All obligations reviewed',true,
                          'resolution-1','Qualified review',clock_timestamp(),%s,'authorized')
                """,
                (uuid4(), departure_id, mismatched_pet_deposit_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mismatched_pet_review.value.sqlstate == "23514"
    connection.execute(
        """
        INSERT INTO app.pet_deposit_refund_reviews(
            id, pet_departure_id, pet_deposit_id,
            obligations_reviewed_usd_cents, review_findings,
            all_pet_obligations_resolved, resolution_reference, reason,
            reviewed_at, reviewed_by, authorization_reference
        ) VALUES (%s,%s,%s,0,'All obligations reviewed',true,
                  'resolution-2','Qualified review',clock_timestamp(),%s,'authorized')
        """,
        (uuid4(), departure_id, matching_pet_deposit_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        """
        SELECT
            (SELECT count(*) FROM app.termination_notices WHERE lease_id=%s),
            (SELECT count(*) FROM app.lease_violation_warnings WHERE lease_id=%s),
            (SELECT count(*) FROM app.lease_pet_approvals WHERE lease_id=%s),
            (SELECT count(*) FROM app.lease_service_terms WHERE lease_id=%s),
            (SELECT count(*) FROM app.lease_pet_departures WHERE lease_id=%s),
            (SELECT count(*) FROM app.pet_deposit_refund_reviews)
        """,
        (lease_id, lease_id, lease_id, lease_id, lease_id),
    ).fetchone() == (1, 1, 1, 1, 1, 1)
    with pytest.raises(Error) as notice_rewrite:
        with connection.transaction():
            connection.execute(
                "UPDATE app.termination_notices SET notice_text='Rewritten' WHERE id=%s",
                (notice_id,),
            )
    assert notice_rewrite.value.sqlstate == "55000"
    table_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='app' AND table_name LIKE 'rent_nonpayment_%'"
        ).fetchall()
    }
    assert table_names == {
        "rent_nonpayment_cases",
        "rent_nonpayment_events",
        "rent_nonpayment_evaluation_principals",
    }


def test_lease_persistence_migration_is_forward_only() -> None:
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / "20260826_23_lease_persistence.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "20260826_22"' in source
    assert "Lease, signer, and occupancy migration is forward-only" in source


def test_runtime_role_can_read_but_not_mutate_lease_storage(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    assert runtime_url is not None
    runtime_url = runtime_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(runtime_url) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.leases', 'SELECT'),
                has_table_privilege(current_user, 'app.leases', 'INSERT'),
                has_table_privilege(current_user, 'app.lease_signers', 'UPDATE'),
                has_table_privilege(current_user, 'app.occupancies', 'DELETE'),
                has_table_privilege(current_user, 'app.lease_revisions', 'SELECT')
            """
        ).fetchone()
        assert privileges == (True, False, False, False, True)


def test_reservation_resulting_lease_reference_is_real_and_restrictive(
    connection: Connection[tuple[object, ...]],
) -> None:
    constraint = connection.execute(
        """
        SELECT confrelid::regclass::text, confdeltype, condeferrable
        FROM pg_constraint
        WHERE conrelid='app.reservations'::regclass
          AND conname='reservations_resulting_lease_fkey'
        """
    ).fetchone()
    assert constraint == ("app.leases", "r", True)
