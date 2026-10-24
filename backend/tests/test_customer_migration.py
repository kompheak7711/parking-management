"""PostgreSQL tests for canonical Customer identity and audit history."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5
from pathlib import Path
from runpy import run_path
from threading import Barrier
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.sql import SQL

from property_rental.customer import (
    CustomerReuseRequired,
    CustomerService,
    PostgresCustomerRepository,
)
from property_rental.customer_api import (
    CustomerIdempotencyKeyReused,
    CustomerResourceUnavailable,
    PostgresCustomerResourceFlow,
    PostgresCustomerSearchRateGuard,
)


def test_migration_backfill_tolerates_a_malformed_legacy_email_domain() -> None:
    migration = run_path(
        str(Path(__file__).parents[1] / "migrations/versions/20260824_16_customer_deactivation.py")
    )
    digest = cast(Callable[[str], str], migration["_legacy_email_match_digest"])

    assert digest("user@a..com") == md5(b"user@a..com", usedforsecurity=False).hexdigest()


def test_migration_streams_and_batches_legacy_email_match_keys() -> None:
    migration_path = (
        Path(__file__).parents[1] / "migrations/versions/20260824_16_customer_deactivation.py"
    )
    migration = run_path(str(migration_path))
    batch_size = cast(int, migration["EMAIL_BACKFILL_BATCH_SIZE"])
    backfill = cast(Callable[[object], None], migration["_backfill_legacy_email_match_keys"])
    rows = [(uuid4(), f"customer-{index}@example.com") for index in range(batch_size + 1)]

    class StreamingResult:
        def __init__(self) -> None:
            self.closed = False
            self.offset = 0
            self.fetch_sizes: list[int] = []

        def close(self) -> None:
            self.closed = True

        def fetchmany(self, size: int) -> list[tuple[UUID, str]]:
            self.fetch_sizes.append(size)
            batch = rows[self.offset : self.offset + size]
            self.offset += len(batch)
            return batch

    class ConnectionDouble:
        def __init__(self) -> None:
            self.result = StreamingResult()
            self.option_calls: list[dict[str, object]] = []
            self.insert_batches: list[list[dict[str, object]]] = []

        def execution_options(self, **options: object) -> ConnectionDouble:
            self.option_calls.append(options)
            return self

        def execute(self, statement: object, parameters: object = None) -> StreamingResult | None:
            del statement
            if parameters is None:
                return self.result
            self.insert_batches.append(cast(list[dict[str, object]], parameters))
            return None

    connection = ConnectionDouble()
    backfill(connection)

    assert connection.option_calls == [
        {"stream_results": True, "yield_per": batch_size},
        {"stream_results": False, "yield_per": None},
    ]
    assert connection.result.closed is True
    assert connection.result.fetch_sizes == [batch_size, batch_size, batch_size]
    assert [len(batch) for batch in connection.insert_batches] == [batch_size, 1]
    assert connection.insert_batches[0][0]["customer_id"] == rows[0][0]
    assert (
        connection.insert_batches[0][0]["match_digest"]
        == md5(b"customer-0@example.com", usedforsecurity=False).hexdigest()
    )
    upgrade_source = migration_path.read_text().split("def upgrade()", 1)[1]
    assert (
        upgrade_source.index("LOCK TABLE app.customers IN EXCLUSIVE MODE")
        < upgrade_source.index("_backfill_legacy_email_match_keys(connection)")
        < upgrade_source.index("CREATE FUNCTION app.sync_customer_email_match_key()")
    )


def test_customer_command_paths_archive_the_exact_target_before_global_cleanup() -> None:
    migration_source = (
        Path(__file__).parents[1] / "migrations/versions/20260824_16_customer_deactivation.py"
    ).read_text()
    function_starts = [
        migration_source.index("CREATE FUNCTION app.get_customer_command("),
        migration_source.index("CREATE FUNCTION app.execute_customer_create("),
        migration_source.index("CREATE FUNCTION app.execute_customer_update("),
        migration_source.index("CREATE FUNCTION app.execute_customer_deactivate("),
    ]

    for index, start in enumerate(function_starts):
        end = (
            function_starts[index + 1]
            if index + 1 < len(function_starts)
            else len(migration_source)
        )
        function_source = migration_source[start:end]
        archive_position = function_source.index("PERFORM app.archive_expired_customer_command(")
        purge_position = function_source.index("PERFORM app.purge_expired_customer_commands(1000);")
        assert archive_position < purge_position


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def actor_and_property(connection: Connection[tuple[object, ...]]) -> tuple[UUID, UUID]:
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s, %s, 'Customer Tester', 'Customer Tester', 'active', 'optional', 'test')
        """,
        (actor_id, f"customer-{actor_id}"),
    )
    existing = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing is not None:
        return actor_id, UUID(str(existing[0]))
    property_id = uuid4()
    connection.execute(
        "INSERT INTO app.properties (id, name, created_by, updated_by) "
        "VALUES (%s, 'Customer Test Property', %s, %s)",
        (property_id, actor_id, actor_id),
    )
    return actor_id, property_id


def insert_customer(
    connection: Connection[tuple[object, ...]],
    actor_id: UUID,
    *,
    customer_id: UUID | None = None,
    legal_name: str = "Dara Sok",
    phone_number: str | None = None,
    email_address: str | None = None,
) -> UUID:
    stored_id = uuid4() if customer_id is None else customer_id
    connection.execute(
        """
        INSERT INTO app.customers (
            id, legal_name, phone_number, email_address, created_by, updated_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (stored_id, legal_name, phone_number, email_address, actor_id, actor_id),
    )
    return stored_id


def test_migration_persists_canonical_customer_without_fixed_type(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = insert_customer(connection, actor_id)

    columns = {
        row[0]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'app' AND table_name = 'customers'"
        ).fetchall()
    }
    stored = connection.execute(
        "SELECT id, legal_name, phone_number, email_address, version "
        "FROM app.customers WHERE id = %s",
        (customer_id,),
    ).fetchone()

    assert stored == (customer_id, "Dara Sok", None, None, 1)
    assert "customer_type" not in columns
    assert "category" not in columns


def test_customer_audit_history_has_bounded_pagination_index(
    connection: Connection[tuple[object, ...]],
) -> None:
    definition = connection.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname = 'app' "
        "AND indexname = 'audit_events_customer_history_page_idx'"
    ).fetchone()

    assert definition is not None
    normalized = " ".join(str(definition[0]).split())
    assert "(property_id, customer_id, occurred_at DESC, id DESC)" in normalized
    assert "WHERE (customer_id IS NOT NULL)" in normalized

    search_indexes: dict[str, str] = {
        str(index_name): str(index_definition)
        for index_name, index_definition in connection.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'app' "
            "AND indexname IN ("
            "'customers_legal_name_search_prefix_idx', "
            "'customers_email_search_prefix_idx', "
            "'customers_phone_search_prefix_idx')"
        ).fetchall()
    }
    assert set(search_indexes) == {
        "customers_legal_name_search_prefix_idx",
        "customers_email_search_prefix_idx",
        "customers_phone_search_prefix_idx",
    }
    assert all("text_pattern_ops" in definition for definition in search_indexes.values())
    normalized_search_indexes = {
        name: definition.replace('"left"', "left") for name, definition in search_indexes.items()
    }
    assert (
        "left(lower(legal_name), 255)"
        in normalized_search_indexes["customers_legal_name_search_prefix_idx"]
    )
    assert (
        "left(lower(email_address), 320)"
        in normalized_search_indexes["customers_email_search_prefix_idx"]
    )
    assert (
        "left(regexp_replace(phone_number"
        in normalized_search_indexes["customers_phone_search_prefix_idx"]
    )
    email_match_index = connection.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'app' "
        "AND indexname = 'customer_email_match_keys_digest_idx'"
    ).fetchone()
    assert email_match_index is not None
    assert "(match_digest)" in str(email_match_index[0])
    email_match_function = connection.execute(
        "SELECT pg_get_functiondef('app.sync_customer_email_match_key()'::regprocedure)"
    ).fetchone()
    assert email_match_function is not None
    normalized_match_function = " ".join(str(email_match_function[0]).split()).lower()
    assert "md5(lower" in normalized_match_function
    assert 'collate "c"' in normalized_match_function


def test_bounded_search_index_accepts_legacy_unbounded_customer_name(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    legacy_name = "ក" * 10_000
    customer_id = insert_customer(connection, actor_id, legal_name=legacy_name)

    found = connection.execute(
        "SELECT id FROM app.customers "
        "WHERE left(lower(legal_name), 255) "
        "LIKE left(lower(%s), 255) ESCAPE E'\\\\'",
        (f"{legacy_name[:255]}%",),
    ).fetchone()

    assert found == (customer_id,)


@pytest.mark.parametrize("legal_name", ["", "   ", " Dara Sok "])
def test_migration_rejects_invalid_customer_name(
    connection: Connection[tuple[object, ...]], legal_name: str
) -> None:
    actor_id, _ = actor_and_property(connection)

    with pytest.raises(Error) as raised:
        insert_customer(connection, actor_id, legal_name=legal_name)

    assert raised.value.sqlstate == "23514"


@pytest.mark.parametrize(
    "statement",
    [
        SQL("UPDATE app.customers SET id = %s, version = version + 1"),
        SQL(
            "UPDATE app.customers "
            "SET created_at = created_at + interval '1 second', version = version + 1"
        ),
        SQL("DELETE FROM app.customers"),
        SQL("TRUNCATE app.customers"),
    ],
)
def test_migration_rejects_customer_identity_or_history_loss(
    connection: Connection[tuple[object, ...]], statement: SQL
) -> None:
    actor_id, _ = actor_and_property(connection)
    insert_customer(connection, actor_id)

    with pytest.raises(Error) as raised:
        parameters = (uuid4(),) if "%s" in statement.as_string() else ()
        connection.execute(statement, parameters)

    assert raised.value.sqlstate in {"55000", "0A000"}


def test_protected_update_preserves_previous_and_resulting_contact_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = uuid4()
    created_event = uuid4()
    updated_event = uuid4()
    created = connection.execute(
        "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Dara Sok", "012345678", None, None, None, actor_id, created_event),
    ).fetchone()
    updated = connection.execute(
        "SELECT * FROM app.update_customer(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            customer_id,
            "Dara Sok",
            "098765432",
            "dara@example.com",
            None,
            None,
            1,
            actor_id,
            updated_event,
        ),
    ).fetchone()
    audit = connection.execute(
        "SELECT action, previous_state, resulting_state FROM app.audit_events "
        "WHERE customer_id = %s ORDER BY occurred_at, id",
        (customer_id,),
    ).fetchall()

    assert created is not None and created[-1] == 1
    assert updated is not None and updated[-1] == 2
    assert [row[0] for row in audit] == ["customer.created", "customer.updated"]
    previous = cast(dict[str, object], audit[1][1])
    resulting = cast(dict[str, object], audit[1][2])
    assert previous["phone_number"] == "012345678"
    assert resulting["phone_number"] == "098765432"
    assert previous["customer_id"] == str(customer_id)


def test_version_conflict_changes_neither_customer_nor_audit(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = uuid4()
    connection.execute(
        "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Dara Sok", None, None, None, None, actor_id, uuid4()),
    )

    rejected = connection.execute(
        "SELECT * FROM app.update_customer(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Changed", None, None, None, None, 9, actor_id, uuid4()),
    ).fetchone()
    stored = connection.execute(
        "SELECT legal_name, version FROM app.customers WHERE id = %s", (customer_id,)
    ).fetchone()
    count = connection.execute(
        "SELECT count(*) FROM app.audit_events WHERE customer_id = %s", (customer_id,)
    ).fetchone()

    assert rejected is None
    assert stored == ("Dara Sok", 1)
    assert count == (1,)


def test_runtime_repository_requires_reuse_decision_and_preserves_update_history(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Customer Runtime', 'Customer Runtime', 'active', 'optional', 'test')
            """,
            (actor_id, f"customer-runtime-{actor_id}"),
        )
        existing_property = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing_property is None:
            property_id = uuid4()
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Runtime Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing_property[0]))

    repository = PostgresCustomerRepository(runtime_url, actor_id)
    service = CustomerService(repository)
    email = f"{uuid4()}@example.com"
    created = service.create(
        uuid4(),
        legal_name="Dara Sok",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        email_address=email,
    )
    with pytest.raises(CustomerReuseRequired):
        service.create(
            uuid4(),
            legal_name="Dara S.",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            email_address=email.upper(),
        )
    idn = service.create(
        uuid4(),
        legal_name="IDN Customer",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        email_address="user@bücher.de",
    )
    assert idn.email_address == "user@xn--bcher-kva.de"
    with pytest.raises(CustomerReuseRequired):
        service.create(
            uuid4(),
            legal_name="Equivalent ASCII IDN Customer",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            email_address="user@xn--bcher-kva.de",
        )
    updated = service.update(
        created,
        legal_name="Dara Sok",
        phone_number="012345678",
        email_address=email,
        contact_address="Phnom Penh",
        memo=None,
    )

    assert updated.customer_id == created.customer_id
    assert updated.version == 2
    with psycopg.connect(runtime_url) as runtime:
        with pytest.raises(Error) as raised:
            runtime.execute("DELETE FROM app.customers WHERE id = %s", (created.customer_id,))
        assert raised.value.sqlstate == "42501"
        runtime.rollback()
        actions = runtime.execute(
            "SELECT action FROM app.audit_events WHERE customer_id = %s ORDER BY occurred_at, id",
            (created.customer_id,),
        ).fetchall()
    assert [row[0] for row in actions] == ["customer.created", "customer.updated"]
    flow = PostgresCustomerResourceFlow(runtime_url)
    first_page = flow.history(
        updated.customer_id,
        property_id=property_id,
        limit=1,
        cursor=None,
    )
    assert len(first_page.items) == 1
    assert first_page.next_cursor is not None
    second_page = flow.history(
        updated.customer_id,
        property_id=property_id,
        limit=1,
        cursor=first_page.next_cursor,
    )
    assert len(second_page.items) == 1
    assert second_page.next_cursor is None


def test_runtime_customer_search_accepts_maximum_escaped_prefix(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    customer_id = uuid4()
    legal_name = "%" * 255
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Customer Search', 'Customer Search',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-search-{actor_id}"),
        )
        existing_property = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing_property is None:
            property_id = uuid4()
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Search Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing_property[0]))
        insert_customer(
            admin,
            actor_id,
            customer_id=customer_id,
            legal_name=legal_name,
        )

    page = PostgresCustomerResourceFlow(runtime_url).list(
        property_id,
        query=legal_name,
        active=True,
        limit=20,
        cursor=None,
    )

    assert [item.customer.customer_id for item in page.items] == [customer_id]


def test_runtime_reuse_decision_serializes_concurrent_create_and_update(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Reuse Concurrency', 'Reuse Concurrency',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-reuse-concurrency-{actor_id}"),
        )
        if admin.execute("SELECT id FROM app.properties").fetchone() is None:
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Reuse Concurrency Property', %s, %s)",
                (uuid4(), actor_id, actor_id),
            )

    service = CustomerService(PostgresCustomerRepository(runtime_url, actor_id))
    current = service.create(
        uuid4(), legal_name="Existing Customer", id_document_number=f"ID-{uuid4().hex[:12]}"
    )
    shared_email = f"concurrent-{uuid4()}@example.com"
    barrier = Barrier(2)

    def create_customer() -> str:
        barrier.wait()
        try:
            service.create(
                uuid4(),
                legal_name="New Customer",
                id_document_number=f"ID-{uuid4().hex[:12]}",
                email_address=shared_email.upper(),
            )
        except CustomerReuseRequired:
            return "reuse_required"
        return "created"

    def update_customer() -> str:
        barrier.wait()
        try:
            service.update(
                current,
                legal_name=current.legal_name,
                phone_number=None,
                email_address=shared_email,
                contact_address=None,
                memo=None,
            )
        except CustomerReuseRequired:
            return "reuse_required"
        return "updated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(create_customer)
        update_future = executor.submit(update_customer)
        results = {create_future.result(), update_future.result()}

    assert results in ({"created", "reuse_required"}, {"updated", "reuse_required"})
    with psycopg.connect(runtime_url) as runtime:
        matching = runtime.execute(
            "SELECT count(*) FROM app.customers WHERE lower(email_address) = %s",
            (shared_email,),
        ).fetchone()
    assert matching == (1,)


def test_runtime_reuse_lock_wait_is_bounded_and_reported_unavailable(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Lock Timeout', 'Lock Timeout',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-lock-timeout-{actor_id}"),
        )
        existing = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing is None:
            property_id = uuid4()
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Lock Timeout Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing[0]))

    email = f"blocked-{uuid4()}@example.com"
    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"customer-email:{email}",),
        )
        started = monotonic()
        with pytest.raises(CustomerResourceUnavailable):
            PostgresCustomerResourceFlow(runtime_url).create(
                property_id,
                customer_id=uuid4(),
                legal_name="Bounded Lock Wait",
                id_document_number=f"ID-{uuid4().hex[:12]}",
                phone_number=None,
                email_address=email,
                contact_address=None,
                memo=None,
                confirmed_distinct=False,
                actor_id=str(actor_id),
                idempotency_key=uuid4(),
                request_digest="a" * 64,
            )
        elapsed = monotonic() - started

    assert 0.5 <= elapsed < 2.5


def test_runtime_customer_write_wait_is_bounded_on_the_work_connection(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    customer_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Write Timeout', 'Write Timeout',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-write-timeout-{actor_id}"),
        )
        existing = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing is None:
            property_id = uuid4()
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Write Timeout Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing[0]))
        admin.execute(
            "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
            (customer_id, "Bounded Write", None, None, None, None, actor_id, uuid4()),
        )

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute("SELECT id FROM app.customers WHERE id = %s FOR UPDATE", (customer_id,))
        started = monotonic()
        with pytest.raises(CustomerResourceUnavailable):
            PostgresCustomerResourceFlow(runtime_url).update(
                customer_id,
                legal_name="Bounded Write Updated",
                phone_number=None,
                email_address=None,
                contact_address=None,
                memo=None,
                confirmed_distinct=False,
                expected_version=1,
                actor_id=str(actor_id),
                idempotency_key=uuid4(),
                request_digest="b" * 64,
            )
        elapsed = monotonic() - started

    assert 0.5 <= elapsed < 2.5


def test_runtime_deactivation_preserves_customer_and_records_history(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    customer_id = uuid4()
    event_id = uuid4()
    rejected_event_id = uuid4()
    repeated_event_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Deactivation Tester', 'Deactivation Tester',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-deactivation-{actor_id}"),
        )
        if admin.execute("SELECT id FROM app.properties").fetchone() is None:
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Deactivation Property', %s, %s)",
                (uuid4(), actor_id, actor_id),
            )
        admin.execute(
            "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                customer_id,
                "Dara Sok",
                None,
                None,
                None,
                None,
                actor_id,
                uuid4(),
            ),
        )

    with psycopg.connect(runtime_url) as runtime:
        with pytest.raises(Error) as blank_reason:
            runtime.execute(
                "SELECT * FROM app.deactivate_customer(%s, %s, %s, %s, %s)",
                (customer_id, "\t\n", 1, actor_id, uuid4()),
            )
        assert blank_reason.value.sqlstate == "23514"

    with psycopg.connect(runtime_url) as runtime:
        rejected = runtime.execute(
            "SELECT * FROM app.deactivate_customer(%s, %s, %s, %s, %s)",
            (customer_id, "Must retain version guard", None, actor_id, rejected_event_id),
        ).fetchone()
        preserved = runtime.execute(
            "SELECT version, deactivated_at FROM app.customers WHERE id = %s",
            (customer_id,),
        ).fetchone()
        rejected_audit = runtime.execute(
            "SELECT id FROM app.audit_events WHERE id = %s",
            (rejected_event_id,),
        ).fetchone()
        deactivated = runtime.execute(
            "SELECT * FROM app.deactivate_customer(%s, %s, %s, %s, %s)",
            (customer_id, "Duplicate entered distinctly", 1, actor_id, event_id),
        ).fetchone()
        stored = runtime.execute(
            "SELECT id, version, deactivated_at, deactivation_reason "
            "FROM app.customers WHERE id = %s",
            (customer_id,),
        ).fetchone()
        audit = runtime.execute(
            "SELECT action, previous_state, resulting_state FROM app.audit_events WHERE id = %s",
            (event_id,),
        ).fetchone()

    assert rejected is None
    assert preserved == (1, None)
    assert rejected_audit is None
    assert deactivated is not None and deactivated[0] == customer_id
    assert stored is not None and stored[0] == customer_id and stored[1] == 2
    assert stored[2] is not None and stored[3] == "Duplicate entered distinctly"
    assert audit is not None and audit[0] == "customer.deactivated"
    assert cast(dict[str, object], audit[1])["active"] is True
    assert cast(dict[str, object], audit[2])["active"] is False

    with psycopg.connect(runtime_url) as runtime:
        with pytest.raises(Error) as repeated:
            runtime.execute(
                "SELECT * FROM app.deactivate_customer(%s, %s, %s, %s, %s)",
                (customer_id, "A conflicting second reason", 2, actor_id, repeated_event_id),
            )
        assert repeated.value.sqlstate == "23514"

    with psycopg.connect(runtime_url) as runtime:
        repeated_state = runtime.execute(
            "SELECT version, deactivation_reason FROM app.customers WHERE id = %s",
            (customer_id,),
        ).fetchone()
        repeated_audit = runtime.execute(
            "SELECT id FROM app.audit_events WHERE id = %s",
            (repeated_event_id,),
        ).fetchone()
    assert repeated_state == (2, "Duplicate entered distinctly")
    assert repeated_audit is None

    with psycopg.connect(runtime_url) as runtime:
        with pytest.raises(Error) as raised:
            runtime.execute(
                "SELECT * FROM app.update_customer(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    customer_id,
                    "Changed after deactivation",
                    None,
                    None,
                    None,
                    None,
                    2,
                    actor_id,
                    uuid4(),
                ),
            )
        assert raised.value.sqlstate == "55000"


def test_runtime_customer_commands_replay_original_results_after_later_changes(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    customer_id = uuid4()
    create_key = uuid4()
    first_update_key = uuid4()
    later_update_key = uuid4()
    deactivate_key = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Command Replay', 'Command Replay',
                      'active', 'optional', 'test')
            """,
            (actor_id, f"customer-command-replay-{actor_id}"),
        )
        property_row = admin.execute("SELECT id FROM app.properties LIMIT 1").fetchone()
        if property_row is None:
            property_id = uuid4()
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Command Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(property_row[0]))

    flow = PostgresCustomerResourceFlow(runtime_url)
    created = flow.create(
        property_id,
        customer_id=customer_id,
        legal_name="Original Customer",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        phone_number=None,
        email_address="original@example.com",
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        actor_id=str(actor_id),
        idempotency_key=create_key,
        request_digest="1" * 64,
    )
    first_update = flow.update(
        customer_id,
        legal_name="First Updated Customer",
        phone_number=None,
        email_address="original@example.com",
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        expected_version=1,
        actor_id=str(actor_id),
        idempotency_key=first_update_key,
        request_digest="2" * 64,
    )
    later_update = flow.update(
        customer_id,
        legal_name="Later Authorized Customer",
        phone_number=None,
        email_address="original@example.com",
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        expected_version=2,
        actor_id=str(actor_id),
        idempotency_key=later_update_key,
        request_digest="3" * 64,
    )

    assert created.customer.version == 1
    assert first_update.customer.version == 2
    assert later_update.customer.version == 3
    replayed_create = flow.create(
        property_id,
        customer_id=customer_id,
        legal_name="Original Customer",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        phone_number=None,
        email_address="original@example.com",
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        actor_id=str(actor_id),
        idempotency_key=create_key,
        request_digest="1" * 64,
    )
    replayed_update = flow.command_status(
        property_id=property_id,
        customer_id=customer_id,
        action="update",
        idempotency_key=first_update_key,
        actor_id=str(actor_id),
    )
    assert replayed_create.customer.legal_name == "Original Customer"
    assert replayed_create.customer.version == 1
    assert replayed_update.recorded is True
    assert replayed_update.record is not None
    assert replayed_update.record.customer.legal_name == "First Updated Customer"
    assert replayed_update.record.customer.version == 2
    assert replayed_update.event_id is not None
    exact_history = flow.command_history(
        property_id=property_id,
        customer_id=customer_id,
        event_id=replayed_update.event_id,
    )
    assert [event.event_id for event in exact_history.items] == [replayed_update.event_id]

    with pytest.raises(CustomerIdempotencyKeyReused):
        flow.create(
            property_id,
            customer_id=customer_id,
            legal_name="Different Input",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            phone_number=None,
            email_address="different@example.com",
            contact_address=None,
            memo=None,
            confirmed_distinct=False,
            actor_id=str(actor_id),
            idempotency_key=create_key,
            request_digest="4" * 64,
        )

    second_actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Scoped Command', 'Scoped Command',
                      'active', 'optional', 'test')
            """,
            (second_actor_id, f"customer-command-scope-{second_actor_id}"),
        )
    independently_scoped = flow.create(
        property_id,
        customer_id=uuid4(),
        legal_name="Independently Scoped Customer",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        actor_id=str(second_actor_id),
        idempotency_key=create_key,
        request_digest="5" * 64,
    )
    same_actor_different_action = flow.update(
        customer_id,
        legal_name="Action Scoped Customer",
        phone_number=None,
        email_address="original@example.com",
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        expected_version=3,
        actor_id=str(actor_id),
        idempotency_key=create_key,
        request_digest="6" * 64,
    )
    assert independently_scoped.customer.version == 1
    assert same_actor_different_action.customer.version == 4
    deactivated = flow.deactivate(
        customer_id,
        reason="Identity retained after service ended",
        expected_version=4,
        actor_id=str(actor_id),
        idempotency_key=deactivate_key,
        request_digest="7" * 64,
    )
    assert deactivated.customer.version == 5
    assert deactivated.active is False

    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            "UPDATE app.customer_commands "
            "SET created_at = statement_timestamp() - interval '2 days', "
            "expires_at = statement_timestamp() - interval '1 day' "
            "WHERE actor_id = %s AND property_id = %s "
            "AND ((action = 'create' AND idempotency_key = %s) "
            "OR (action = 'deactivate' AND idempotency_key = %s))",
            (actor_id, property_id, create_key, deactivate_key),
        )
    expired = flow.command_status(
        property_id=property_id,
        customer_id=customer_id,
        action="create",
        idempotency_key=create_key,
        actor_id=str(actor_id),
    )
    assert expired.recorded is True
    assert expired.expired is True
    assert expired.record is not None
    assert expired.record.customer.legal_name == "Original Customer"
    assert expired.record.customer.version == 1
    assert expired.record.active is True
    assert expired.record.deactivated_at is None
    assert expired.record.deactivation_reason is None
    assert expired.event_id is not None
    expired_deactivation = flow.command_status(
        property_id=property_id,
        customer_id=customer_id,
        action="deactivate",
        idempotency_key=deactivate_key,
        actor_id=str(actor_id),
        request_digest="7" * 64,
    )
    assert expired_deactivation.recorded is True
    assert expired_deactivation.expired is True
    assert expired_deactivation.record is not None
    assert expired_deactivation.record.customer.version == 5
    assert expired_deactivation.record.deactivated_at == deactivated.deactivated_at
    assert expired_deactivation.record.deactivation_reason == deactivated.deactivation_reason
    assert expired_deactivation.record.deactivated_at is not None
    assert expired_deactivation.record.deactivated_at.isoformat()
    with pytest.raises(CustomerIdempotencyKeyReused):
        flow.create(
            property_id,
            customer_id=customer_id,
            legal_name="Changed After Archive",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            phone_number=None,
            email_address="changed-after-archive@example.com",
            contact_address=None,
            memo=None,
            confirmed_distinct=False,
            actor_id=str(actor_id),
            idempotency_key=create_key,
            request_digest="8" * 64,
        )
    with psycopg.connect(migrated_database_url) as admin:
        retained = admin.execute(
            "SELECT count(*) FROM app.customer_commands "
            "WHERE actor_id = %s AND property_id = %s "
            "AND action = 'create' AND idempotency_key = %s",
            (actor_id, property_id, create_key),
        ).fetchone()
        tombstone = admin.execute(
            "SELECT customer_id, event_id, request_digest "
            "FROM app.customer_command_tombstones "
            "WHERE actor_id = %s AND property_id = %s "
            "AND action = 'create' AND idempotency_key = %s",
            (actor_id, property_id, create_key),
        ).fetchone()
    assert retained == (0,)
    assert tombstone == (customer_id, expired.event_id, "1" * 64)


def test_customer_search_rate_budget_is_shared_across_guard_instances(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = str(uuid4())
    property_id = uuid4()
    first = PostgresCustomerSearchRateGuard(runtime_url)
    second = PostgresCustomerSearchRateGuard(runtime_url)

    decisions = [
        (first if index % 2 == 0 else second).allow(
            actor_id=actor_id,
            source="198.51.100.7",
            property_id=property_id,
        )
        for index in range(21)
    ]

    assert decisions[:20] == [True] * 20
    assert decisions[20] is False

    existing_actor_id = str(uuid4())
    existing_property_id = uuid4()
    assert first.allow(
        actor_id=existing_actor_id,
        source="198.51.100.8",
        property_id=existing_property_id,
    )
    with psycopg.connect(migrated_database_url) as admin:
        admin.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended('customer-search-rate:bucket-cap', 0))"
        )
        assert second.allow(
            actor_id=existing_actor_id,
            source="198.51.100.8",
            property_id=existing_property_id,
        )


def test_customer_search_rate_buckets_are_persistently_bounded_and_expire(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute("DELETE FROM app.customer_search_rate_windows")
        admin.execute(
            """
            INSERT INTO app.customer_search_rate_windows (
                bucket_key, window_started_at, request_count, updated_at
            )
            SELECT md5(value::text) || md5('bounded-' || value::text),
                   clock_timestamp(), 1, clock_timestamp()
            FROM generate_series(1, 10000) AS value
            """
        )

    guard = PostgresCustomerSearchRateGuard(runtime_url)
    assert not guard.allow(
        actor_id=str(uuid4()),
        source="203.0.113.200",
        property_id=uuid4(),
    )

    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            "UPDATE app.customer_search_rate_windows "
            "SET updated_at = clock_timestamp() - interval '61 seconds'"
        )
    assert guard.allow(
        actor_id=str(uuid4()),
        source="203.0.113.201",
        property_id=uuid4(),
    )
    with psycopg.connect(migrated_database_url) as admin:
        count = admin.execute("SELECT count(*) FROM app.customer_search_rate_windows").fetchone()
    assert count == (1,)


def test_migration_is_forward_only(migrated_database_url: str) -> None:
    del migrated_database_url
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260824_14")
