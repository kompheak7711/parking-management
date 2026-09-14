"""Real-PostgreSQL checks for immutable audit-event storage."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from property_rental.audit import (
    AuditConnection,
    AuditEventAppendService,
    AuditEventCommand,
    PostgresAuditEventAppender,
)
from property_rental.audit_api import (
    AuditPageRequest,
    AuthorizedAuditEventQueryService,
    PostgresAuditEventQueryRepository,
    PropertyAuditQuery,
    ResourceAuditQuery,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "migrations" / "versions" / "20260823_10_audit_events.py"


def _migration_database_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for PostgreSQL migration tests")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_to_head() -> str:
    database_url = _migration_database_url()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    return database_url


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_events_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _insert_audit_event(connection: psycopg.Connection[tuple[object, ...]]) -> str:
    event_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO app.audit_events (
            id, occurred_at, business_date, actor_id, action, entity_type,
            entity_id, reason, authorization_reference, property_id,
            previous_state, resulting_state, correlation_id, source, outcome
        ) VALUES (
            %s, CURRENT_TIMESTAMP, CURRENT_DATE, %s, 'lease.created', 'lease',
            %s, 'approved lease creation', 'AUTH-TEST-001', %s, NULL,
            '{"status": "active"}'::jsonb, %s, 'API', 'succeeded'
        )
        """,
        (
            event_id,
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
        ),
    )
    return event_id


def test_audit_migration_is_forward_only() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_audit_event_schema_matches_the_authoritative_contract() -> None:
    database_url = _upgrade_to_head()

    with psycopg.connect(database_url) as connection:
        columns = connection.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'app' AND table_name = 'audit_events'
            ORDER BY ordinal_position
            """
        ).fetchall()
        assert columns == [
            ("id", "uuid", "NO"),
            ("occurred_at", "timestamp with time zone", "NO"),
            ("business_date", "date", "NO"),
            ("actor_id", "uuid", "NO"),
            ("action", "text", "NO"),
            ("entity_type", "text", "NO"),
            ("entity_id", "uuid", "NO"),
            ("reason", "text", "NO"),
            ("authorization_reference", "text", "YES"),
            ("property_id", "uuid", "NO"),
            ("previous_state", "jsonb", "YES"),
            ("resulting_state", "jsonb", "YES"),
            ("correlation_id", "uuid", "NO"),
            ("source", "text", "NO"),
            ("outcome", "text", "NO"),
            ("authorization_evidence", "jsonb", "YES"),
            ("linked_source_event_id", "uuid", "YES"),
            ("customer_id", "uuid", "YES"),
            ("unit_id", "uuid", "YES"),
            ("lease_id", "uuid", "YES"),
        ]

        actor_foreign_keys = connection.execute(
            """
            SELECT count(*)
            FROM information_schema.table_constraints AS constraint_definition
            JOIN information_schema.constraint_column_usage AS column_definition
              ON column_definition.constraint_schema = constraint_definition.constraint_schema
             AND column_definition.constraint_name = constraint_definition.constraint_name
            WHERE constraint_definition.table_schema = 'app'
              AND constraint_definition.table_name = 'audit_events'
              AND constraint_definition.constraint_type = 'FOREIGN KEY'
              AND column_definition.column_name = 'actor_id'
            """
        ).fetchone()
        assert actor_foreign_keys == (0,)

        index_definitions = {
            row[0]
            for row in connection.execute(
                """
                SELECT indexdef
                FROM pg_catalog.pg_indexes
                WHERE schemaname = 'app' AND tablename = 'audit_events'
                """
            ).fetchall()
        }
        assert any(
            "(entity_type, entity_id, occurred_at, id)" in definition
            for definition in index_definitions
        )
        assert any("(actor_id, occurred_at DESC)" in definition for definition in index_definitions)
        assert any("(correlation_id)" in definition for definition in index_definitions)
        assert any("(business_date)" in definition for definition in index_definitions)
        assert any(
            "(property_id, occurred_at DESC, id DESC)" in definition
            for definition in index_definitions
        )
        assert any("(property_id, customer_id)" in definition for definition in index_definitions)
        assert any("(property_id, unit_id)" in definition for definition in index_definitions)
        assert any("(property_id, lease_id)" in definition for definition in index_definitions)


def test_audit_event_constraints_reject_invalid_rows() -> None:
    database_url = _upgrade_to_head()

    with psycopg.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO app.audit_events (
                    id, occurred_at, business_date, actor_id, action, entity_type,
                    entity_id, reason, property_id, resulting_state,
                    correlation_id, source, outcome
                ) VALUES (
                    %s, CURRENT_TIMESTAMP, CURRENT_DATE, %s, 'lease.created',
                    'lease', %s, 'test reason', %s, '{"status": "active"}'::jsonb,
                    %s, 'BACKGROUND', 'succeeded'
                )
                """,
                (
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                ),
            )


def test_database_rejects_blank_authorization_reference() -> None:
    database_url = _upgrade_to_head()

    with psycopg.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO app.audit_events (
                    id, occurred_at, business_date, actor_id, action, entity_type,
                    entity_id, reason, authorization_reference, property_id,
                    resulting_state, correlation_id, source, outcome
                ) VALUES (
                    %s, CURRENT_TIMESTAMP, CURRENT_DATE, %s, 'lease.created',
                    'lease', %s, 'test reason', '   ', %s,
                    '{"status": "active"}'::jsonb, %s, 'API', 'succeeded'
                )
                """,
                tuple(str(uuid4()) for _ in range(5)),
            )


def test_database_controls_prohibit_audit_event_mutation() -> None:
    database_url = _upgrade_to_head()

    with psycopg.connect(database_url, autocommit=True) as connection:
        event_id = _insert_audit_event(connection)
        audit_before = connection.execute(
            "SELECT to_jsonb(event) FROM app.audit_events event ORDER BY id"
        ).fetchall()

        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE app.audit_events SET reason = 'changed' WHERE id = %s",
                (event_id,),
            )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM app.audit_events WHERE id = %s", (event_id,))
        # The typed inspection-command source now rejects this before the trigger.
        with pytest.raises(
            psycopg.errors.FeatureNotSupported,
            match="cannot truncate a table referenced in a foreign key constraint",
        ):
            connection.execute("TRUNCATE TABLE app.audit_events")
        assert (
            connection.execute(
                "SELECT to_jsonb(event) FROM app.audit_events event ORDER BY id"
            ).fetchall()
            == audit_before
        )

        privileges = connection.execute(
            """
            SELECT
                has_table_privilege('prm_runtime', 'app.audit_events', 'SELECT'),
                has_table_privilege('prm_runtime', 'app.audit_events', 'INSERT'),
                has_table_privilege('prm_runtime', 'app.audit_events', 'UPDATE'),
                has_table_privilege('prm_runtime', 'app.audit_events', 'DELETE'),
                has_table_privilege('prm_runtime', 'app.audit_events', 'TRUNCATE')
            """
        ).fetchone()
        assert privileges == (True, True, False, False, False)


def test_postgres_append_and_authorized_query_round_trip_is_lossless() -> None:
    _upgrade_to_head()
    runtime_url = os.environ["APP_DATABASE_URL"]
    property_id = UUID("00000000-0000-0000-0000-000000000701")
    actor_id = UUID("00000000-0000-0000-0000-000000000702")
    resource_id = UUID("00000000-0000-0000-0000-000000000703")
    payment_id = UUID("00000000-0000-0000-0000-000000000710")
    correlation_id = UUID("00000000-0000-0000-0000-000000000704")
    linked_id = UUID("00000000-0000-0000-0000-000000000705")
    event_id = UUID("00000000-0000-0000-0000-000000000706")
    null_reference_event_id = UUID("00000000-0000-0000-0000-000000000708")
    direct_customer_event_id = UUID("00000000-0000-0000-0000-000000000709")
    customer_id = UUID("00000000-0000-0000-0000-000000000707")

    with psycopg.connect(runtime_url) as connection:
        event = AuditEventAppendService(
            appender=PostgresAuditEventAppender(cast(AuditConnection, connection)),
            clock=lambda: datetime(2026, 8, 23, 2, 0, tzinfo=UTC),
            event_id_factory=lambda: event_id,
        ).append(
            AuditEventCommand(
                actor_id=actor_id,
                property_id=property_id,
                action="lease.created",
                target_type="payment",
                target_id=payment_id,
                reason="approved lease creation",
                authorization_reference="AUTH-LEASE-001",
                previous_state=None,
                resulting_state={"status": "active", "customerId": str(customer_id)},
                correlation_id=correlation_id,
                outcome="succeeded",
                source="API",
                authorization_evidence={"capability": "audit.append"},
                linked_source_event_id=linked_id,
                customer_id=customer_id,
                lease_id=resource_id,
            )
        )
        AuditEventAppendService(
            appender=PostgresAuditEventAppender(cast(AuditConnection, connection)),
            clock=lambda: datetime(2026, 8, 23, 0, 30, tzinfo=UTC),
            event_id_factory=lambda: direct_customer_event_id,
        ).append(
            AuditEventCommand(
                actor_id=actor_id,
                property_id=property_id,
                action="customer.updated",
                target_type="customer",
                target_id=customer_id,
                reason="customer record updated",
                authorization_reference=None,
                previous_state={"status": "pending"},
                resulting_state={"status": "active"},
                correlation_id=correlation_id,
                outcome="succeeded",
                source="API",
            )
        )
        assert event.event_id == event_id
        AuditEventAppendService(
            appender=PostgresAuditEventAppender(cast(AuditConnection, connection)),
            clock=lambda: datetime(2026, 8, 23, 1, 0, tzinfo=UTC),
            event_id_factory=lambda: null_reference_event_id,
        ).append(
            AuditEventCommand(
                actor_id=actor_id,
                property_id=property_id,
                action="lease.validated",
                target_type="lease",
                target_id=resource_id,
                reason="validated without an authorization reference",
                authorization_reference=None,
                previous_state={"status": "draft"},
                resulting_state={"status": "active"},
                correlation_id=correlation_id,
                outcome="succeeded",
                source="SCHEDULED",
            )
        )

    with psycopg.connect(runtime_url) as connection:
        service = AuthorizedAuditEventQueryService(
            PostgresAuditEventQueryRepository(cast(AuditConnection, connection))
        )
        actor = AuthenticatedActor(
            actor_id=str(actor_id),
            capability_grants=frozenset(
                {
                    CapabilityGrant(
                        capability="audit.view",
                        property_ids=frozenset({str(property_id)}),
                    )
                }
            ),
        )
        page = service.search_property(
            actor,
            PropertyAuditQuery(property_id=property_id, page=AuditPageRequest(limit=10)),
        )
        customer_page = service.search_property(
            actor,
            PropertyAuditQuery(
                property_id=property_id,
                page=AuditPageRequest(limit=10),
                customer_id=customer_id,
            ),
        )
        lease_page = PostgresAuditEventQueryRepository(
            cast(AuditConnection, connection)
        ).resource_timeline(
            property_ids=frozenset({property_id}),
            entity_type="lease",
            query=ResourceAuditQuery(
                resource_type="leases",
                resource_id=resource_id,
                page=AuditPageRequest(limit=10),
            ),
        )

    assert len(page.events) == 3
    restored = next(item for item in page.events if item.event_id == event_id)
    assert restored.event_id == event_id
    assert restored.property_id == property_id
    assert restored.authorization_reference == "AUTH-LEASE-001"
    assert restored.outcome == "succeeded"
    assert restored.linked_source_event_id == linked_id
    assert restored.authorization_evidence == {"capability": "audit.append"}
    assert restored.resulting_state == {
        "status": "active",
        "customerId": str(customer_id),
    }
    null_reference = next(item for item in page.events if item.event_id == null_reference_event_id)
    assert null_reference.authorization_reference is None
    assert {item.event_id for item in customer_page.events} == {
        event_id,
        direct_customer_event_id,
    }
    assert (
        next(item for item in customer_page.events if item.event_id == event_id).customer_id
        == customer_id
    )
    assert {item.event_id for item in lease_page.events} == {
        event_id,
        null_reference_event_id,
    }


def test_postgres_appender_participates_in_the_callers_transaction() -> None:
    _upgrade_to_head()
    runtime_url = os.environ["APP_DATABASE_URL"]
    event_id = UUID("00000000-0000-0000-0000-000000000711")

    with psycopg.connect(runtime_url) as connection:
        with pytest.raises(RuntimeError, match="business mutation failed"):
            with connection.transaction():
                AuditEventAppendService(
                    appender=PostgresAuditEventAppender(cast(AuditConnection, connection)),
                    clock=lambda: datetime(2026, 8, 23, 2, 0, tzinfo=UTC),
                    event_id_factory=lambda: event_id,
                ).append(
                    AuditEventCommand(
                        actor_id=UUID("00000000-0000-0000-0000-000000000712"),
                        property_id=UUID("00000000-0000-0000-0000-000000000713"),
                        action="lease.created",
                        target_type="lease",
                        target_id=UUID("00000000-0000-0000-0000-000000000714"),
                        reason="approved lease creation",
                        authorization_reference="AUTH-LEASE-002",
                        previous_state=None,
                        resulting_state={"status": "active"},
                        correlation_id=UUID("00000000-0000-0000-0000-000000000715"),
                        outcome="succeeded",
                        source="API",
                    )
                )
                raise RuntimeError("business mutation failed")

    with psycopg.connect(runtime_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE id = %s", (event_id,)
        ).fetchone() == (0,)
