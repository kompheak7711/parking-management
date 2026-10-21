"""Role bundles, their assignments and the grant reader (login slice sub-slice L1b-2).

SEC-001 to SEC-003, SEC-020 to SEC-022, API-080, DB-AUTH-001, DB-AUTH-007, DL-074, DL-081 (owner
answers (a) to Q-2026-10-21-161 and (b) to Q-2026-10-21-162): a role bundle of the Property holds
only bundle capabilities of the catalog; every version of a bundle and its capability set is
kept; an account has at most one active assignment of a bundle, removed at most once; the grant
reader gives an active, classified account its assigned bundles' current capabilities and the
Owner account class `identity.manage_access`. Rows written here are rolled back, except the
committed Staff account, its test bundle (unique name) and its assignment of the two-transaction
and runtime-role tests; no Owner is ever committed.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import GrantConnection, PostgresCapabilityGrantReader
from property_rental.identity import CapabilityGrant
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

REVISION = "20270120_177"
PREVIOUS = "20270119_176"
READER = "app.actor_capability_grants(uuid)"
TRIGGER_FUNCTIONS = {
    "app.reject_role_bundle_history_change()",
    "app.guard_role_bundle_change()",
    "app.record_role_bundle_version()",
    "app.require_role_bundle_version_of_bundle()",
    "app.require_role_bundle_capability_version()",
    "app.require_single_active_role_assignment()",
}
TABLES = (
    "app.role_bundles",
    "app.role_bundle_versions",
    "app.role_bundle_capabilities",
    "app.user_role_assignments",
    "app.user_role_assignment_removals",
)
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    "lifecycle_state,mfa_policy_class,provenance) "
    "VALUES (%s,%s,'Bundle Test','bundle-test',%s,%s,'login-slice-l1b-2-test')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    "VALUES (%s,%s,'login-slice-l1b-2-test')"
)
ADD_BUNDLE = (
    "INSERT INTO app.role_bundles(role_bundle_id,property_id,name,version,provenance) "
    "VALUES (%s,%s,%s,%s,'login-slice-l1b-2-test')"
)
ADD_CAPABILITY = (
    "INSERT INTO app.role_bundle_capabilities(role_bundle_id,version,capability_id,grant_path) "
    "VALUES (%s,%s,%s,%s)"
)
NEXT_VERSION = "UPDATE app.role_bundles SET version=version+1,name=%s WHERE role_bundle_id=%s"
ASSIGN = (
    "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,property_id,"
    "provenance) VALUES (%s,%s,%s,%s,'login-slice-l1b-2-test')"
)
REMOVE = (
    "INSERT INTO app.user_role_assignment_removals(assignment_id,reason,provenance) "
    "VALUES (%s,%s,'login-slice-l1b-2-test')"
)
GRANTS = "SELECT capability_id,property_id FROM app.actor_capability_grants(%s)"
APPEND_ONLY = "role bundle history is append-only"
CHANGE_BY_VERSION = "a role bundle changes only its name and its next version"
WITH_VERSION = "role bundle capabilities are written only with their version"
ALREADY_ASSIGNED = "a role bundle is already assigned to this account"


def refused(
    connection: psycopg.Connection[Any],
    error: type[Exception],
    query: str,
    parameters: tuple[Any, ...] = (),
    match: str | None = None,
) -> None:
    with pytest.raises(error, match=match):
        with connection.transaction():
            connection.execute(query, parameters)


def add_account(
    connection: psycopg.Connection[Any],
    account_class: str | None = "staff",
    lifecycle: str = "active",
) -> uuid.UUID:
    actor_id = uuid.uuid4()
    mfa = "required" if account_class in ("owner", "manager") else "optional"
    connection.execute(ADD_ACCOUNT, (actor_id, f"bundle-{actor_id.hex}", lifecycle, mfa))
    if account_class is not None:
        connection.execute(ADD_CLASS, (actor_id, account_class))
    return actor_id


def the_property(connection: psycopg.Connection[Any]) -> uuid.UUID:
    """The single Property; made and committed only when the database has none yet."""
    found = connection.execute("SELECT id FROM app.properties").fetchone()
    if found is not None:
        return cast(uuid.UUID, found[0])
    creator = add_account(connection, None)
    property_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO app.properties (id, name, created_by, updated_by) "
        "VALUES (%s, 'Bundle Test Property', %s, %s)",
        (property_id, creator, creator),
    )
    connection.commit()
    return property_id


def add_bundle(
    connection: psycopg.Connection[Any],
    property_id: uuid.UUID,
    capabilities: tuple[str, ...],
    name: str | None = None,
) -> uuid.UUID:
    bundle_id = uuid.uuid4()
    connection.execute(ADD_BUNDLE, (bundle_id, property_id, name or f"Bundle {bundle_id}", 1))
    for capability in capabilities:
        connection.execute(ADD_CAPABILITY, (bundle_id, 1, capability, "bundle"))
    return bundle_id


def next_version(
    connection: psycopg.Connection[Any],
    bundle_id: uuid.UUID,
    capabilities: tuple[str, ...],
    name: str | None = None,
) -> int:
    connection.execute(NEXT_VERSION, (name or f"Bundle {bundle_id}", bundle_id))
    row = connection.execute(
        "SELECT version FROM app.role_bundles WHERE role_bundle_id=%s", (bundle_id,)
    ).fetchone()
    assert row is not None
    version = cast(int, row[0])
    for capability in capabilities:
        connection.execute(ADD_CAPABILITY, (bundle_id, version, capability, "bundle"))
    return version


def assign(
    connection: psycopg.Connection[Any],
    actor_id: uuid.UUID,
    bundle_id: uuid.UUID,
    property_id: uuid.UUID,
) -> uuid.UUID:
    assignment_id = uuid.uuid4()
    connection.execute(ASSIGN, (assignment_id, actor_id, bundle_id, property_id))
    return assignment_id


def grants(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> set[tuple[str, uuid.UUID]]:
    return {(str(row[0]), row[1]) for row in connection.execute(GRANTS, (actor_id,)).fetchall()}


def test_a_role_bundle_holds_only_bundle_capabilities_of_the_catalog(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-21-161 (a) and Q-2026-10-21-162 (b): `settings.manage`,
    `identity.manage_access`, `rent_nonpayment.evaluate` and unknown names are never in a
    bundle; `billing.generate` is."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        bundle_id = add_bundle(connection, property_id, ("leases.read", "billing.generate"))
        for capability in (
            "settings.manage",
            "identity.manage_access",
            "rent_nonpayment.evaluate",
            "reports.export",
        ):
            refused(
                connection,
                psycopg.errors.ForeignKeyViolation,
                ADD_CAPABILITY,
                (bundle_id, 1, capability, "bundle"),
            )
        for capability, grant_path in (
            ("settings.manage", "per_user"),
            ("identity.manage_access", "owner_class"),
            ("rent_nonpayment.evaluate", "service_principal"),
        ):
            refused(
                connection,
                psycopg.errors.CheckViolation,
                ADD_CAPABILITY,
                (bundle_id, 1, capability, grant_path),
            )
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            ADD_CAPABILITY,
            (bundle_id, 1, "leases.read", "bundle"),
        )
        assert connection.execute(
            "SELECT capability_id FROM app.role_bundle_capabilities WHERE role_bundle_id=%s "
            "ORDER BY capability_id",
            (bundle_id,),
        ).fetchall() == [("billing.generate",), ("leases.read",)]
        connection.rollback()


def test_a_role_bundle_name_is_unique_per_property_and_every_version_is_kept(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        bundle_id = add_bundle(connection, property_id, ("leases.read",), "L1b-2 Front desk")
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            ADD_BUNDLE,
            (uuid.uuid4(), property_id, "L1b-2 Front desk", 1),
        )
        # Review round 1: unique whatever the capital letters; no control or invisible
        # format characters.
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            ADD_BUNDLE,
            (uuid.uuid4(), property_id, "l1b-2 FRONT DESK", 1),
        )
        for name in (
            "",
            " Padded",
            "x" * 129,
            "L1b-2\tDesk",
            "L1b-2 De\u200bsk",
            "L1b-2\ufeffDesk",
            # Review round 3: an isolate direction mark, a C1 control and a tag character.
            "L1b-2\u2067Desk",
            "L1b-2\x85Desk",
            "L1b-2\U000e0041Desk",
        ):
            refused(
                connection,
                psycopg.errors.CheckViolation,
                ADD_BUNDLE,
                (uuid.uuid4(), property_id, name, 1),
            )
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            ADD_BUNDLE,
            (uuid.uuid4(), property_id, "L1b-2 Starts late", 2),
            CHANGE_BY_VERSION,
        )
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            ADD_BUNDLE,
            (uuid.uuid4(), uuid.uuid4(), "L1b-2 No Property", 1),
        )
        refused(
            connection,
            psycopg.errors.CheckViolation,
            "INSERT INTO app.role_bundles(role_bundle_id,property_id,name,version,provenance) "
            "VALUES (%s,%s,'L1b-2 Long provenance',1,%s)",
            (uuid.uuid4(), property_id, "p" * 501),
        )
        assert next_version(connection, bundle_id, ("customers.read",), "L1b-2 Desk") == 2
        for query, parameters in (
            ("UPDATE app.role_bundles SET name='L1b-2 Same' WHERE role_bundle_id=%s", (bundle_id,)),
            (
                "UPDATE app.role_bundles SET version=version+2 WHERE role_bundle_id=%s",
                (bundle_id,),
            ),
            (
                "UPDATE app.role_bundles SET version=version-1 WHERE role_bundle_id=%s",
                (bundle_id,),
            ),
            (
                "UPDATE app.role_bundles SET version=version+1,property_id=%s "
                "WHERE role_bundle_id=%s",
                (uuid.uuid4(), bundle_id),
            ),
            (
                "UPDATE app.role_bundles SET version=version+1,provenance='changed' "
                "WHERE role_bundle_id=%s",
                (bundle_id,),
            ),
            (
                "UPDATE app.role_bundles SET version=version+1,"
                "created_at=created_at-interval '1 day' WHERE role_bundle_id=%s",
                (bundle_id,),
            ),
            (
                "UPDATE app.role_bundles SET version=version+1,role_bundle_id=%s "
                "WHERE role_bundle_id=%s",
                (uuid.uuid4(), bundle_id),
            ),
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                parameters,
                CHANGE_BY_VERSION,
            )
        assert connection.execute(
            "SELECT version,name,recorded_transaction=pg_catalog.pg_current_xact_id() "
            "FROM app.role_bundle_versions WHERE role_bundle_id=%s ORDER BY version",
            (bundle_id,),
        ).fetchall() == [(1, "L1b-2 Front desk", True), (2, "L1b-2 Desk", True)]
        assert connection.execute(
            "SELECT version,capability_id FROM app.role_bundle_capabilities "
            "WHERE role_bundle_id=%s ORDER BY version",
            (bundle_id,),
        ).fetchall() == [(1, "leases.read"), (2, "customers.read")]
        for version, name in ((3, "L1b-2 Desk"), (2, "L1b-2 Front desk"), (1, "L1b-2 Front desk")):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                "INSERT INTO app.role_bundle_versions(role_bundle_id,version,name) "
                "VALUES (%s,%s,%s)",
                (bundle_id, version, name),
                "a role bundle version is written only with its bundle",
            )
        for query in (
            "DELETE FROM app.role_bundles WHERE role_bundle_id=%s",
            "UPDATE app.role_bundle_versions SET name='changed' WHERE role_bundle_id=%s",
            "DELETE FROM app.role_bundle_versions WHERE role_bundle_id=%s",
            "UPDATE app.role_bundle_capabilities SET capability_id='leases.sign' "
            "WHERE role_bundle_id=%s",
            "DELETE FROM app.role_bundle_capabilities WHERE role_bundle_id=%s",
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                (bundle_id,),
                APPEND_ONLY,
            )
        for query in (
            "TRUNCATE app.role_bundles CASCADE",
            "TRUNCATE app.role_bundle_versions CASCADE",
            "TRUNCATE app.role_bundle_capabilities",
        ):
            refused(connection, psycopg.errors.IntegrityConstraintViolation, query, (), APPEND_ONLY)
        # The catalog's own refusal, now that a TRUNCATE of the catalog alone meets the foreign
        # key first (test_capability_catalog_migration.py).
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            "TRUNCATE app.capabilities, app.role_bundle_capabilities",
            (),
            "capability catalog is append-only",
        )
        connection.rollback()


def test_a_bundle_version_takes_capabilities_only_in_the_transaction_that_wrote_it(
    migrated_database_url: str,
) -> None:
    """A recorded version never changes: capabilities are written for the bundle's current
    version only, and only by the transaction that wrote that version. The bundle is committed
    (unique name) so that a later transaction can try."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        bundle_id = add_bundle(connection, property_id, ("leases.read",))
        connection.commit()
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            ADD_CAPABILITY,
            (bundle_id, 1, "leases.sign", "bundle"),
            WITH_VERSION,
        )
        assert next_version(connection, bundle_id, ("leases.read", "customers.read")) == 2
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            ADD_CAPABILITY,
            (bundle_id, 1, "leases.sign", "bundle"),
            WITH_VERSION,
        )
        assert next_version(connection, bundle_id, ("leases.read",)) == 3
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            ADD_CAPABILITY,
            (bundle_id, 2, "leases.sign", "bundle"),
            WITH_VERSION,
        )
        connection.rollback()
        assert connection.execute(
            "SELECT bundle.version,capability.version,capability.capability_id "
            "FROM app.role_bundles AS bundle JOIN app.role_bundle_capabilities AS capability "
            "USING (role_bundle_id) WHERE bundle.role_bundle_id=%s",
            (bundle_id,),
        ).fetchall() == [(1, 1, "leases.read")]
        connection.rollback()


def test_a_reused_transaction_id_alone_cannot_add_to_a_recorded_version(
    migrated_database_url: str,
) -> None:
    """Security review round 1: a logical restore may let a later transaction reuse a recorded
    transaction id, so the version also records its transaction's start time. Set-up: the start
    time of the version just written is moved back with the append-only trigger disabled (owner
    only, rolled back), as a restored row would look."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        bundle_id = add_bundle(connection, property_id, ("leases.read",))
        assert next_version(connection, bundle_id, ("leases.read",)) == 2
        connection.execute(
            "ALTER TABLE app.role_bundle_versions "
            "DISABLE TRIGGER role_bundle_versions_are_append_only"
        )
        connection.execute(
            "UPDATE app.role_bundle_versions SET recorded_transaction_started_at='2000-01-01' "
            "WHERE role_bundle_id=%s AND version=2",
            (bundle_id,),
        )
        connection.execute(
            "ALTER TABLE app.role_bundle_versions "
            "ENABLE TRIGGER role_bundle_versions_are_append_only"
        )
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            ADD_CAPABILITY,
            (bundle_id, 2, "customers.read", "bundle"),
            WITH_VERSION,
        )
        connection.rollback()


def test_a_bundle_is_assigned_once_until_its_assignment_is_removed(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        actor_id = add_account(connection)
        bundle_id = add_bundle(connection, property_id, ("leases.read",))
        first = assign(connection, actor_id, bundle_id, property_id)
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            ASSIGN,
            (uuid.uuid4(), actor_id, bundle_id, property_id),
            ALREADY_ASSIGNED,
        )
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            ASSIGN,
            (uuid.uuid4(), add_account(connection), bundle_id, uuid.uuid4()),
        )
        for reason in ("", "  ", "r" * 501):
            refused(connection, psycopg.errors.CheckViolation, REMOVE, (first, reason))
        # Review round 1: who assigned or removed is a real account (null only for seeds).
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,"
            "property_id,assigned_by_actor_id,provenance) "
            "VALUES (%s,%s,%s,%s,%s,'login-slice-l1b-2-test')",
            (uuid.uuid4(), add_account(connection), bundle_id, property_id, uuid.uuid4()),
        )
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            "INSERT INTO app.user_role_assignment_removals(assignment_id,removed_by_actor_id,"
            "reason,provenance) VALUES (%s,%s,'Unknown remover','login-slice-l1b-2-test')",
            (first, uuid.uuid4()),
        )
        connection.execute(
            "INSERT INTO app.user_role_assignment_removals(assignment_id,removed_by_actor_id,"
            "reason,provenance) VALUES (%s,%s,'Moved to another desk','login-slice-l1b-2-test')",
            (first, add_account(connection, "manager")),
        )
        refused(
            connection, psycopg.errors.UniqueViolation, REMOVE, (first, "Removed a second time")
        )
        second = uuid.uuid4()
        connection.execute(
            "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,"
            "property_id,assigned_by_actor_id,provenance) "
            "VALUES (%s,%s,%s,%s,%s,'login-slice-l1b-2-test')",
            (second, actor_id, bundle_id, property_id, add_account(connection, "manager")),
        )
        for query, parameters in (
            (
                "UPDATE app.user_role_assignments SET actor_id=actor_id WHERE assignment_id=%s",
                first,
            ),
            ("DELETE FROM app.user_role_assignments WHERE assignment_id=%s", second),
            (
                "UPDATE app.user_role_assignment_removals SET reason='changed' "
                "WHERE assignment_id=%s",
                first,
            ),
            ("DELETE FROM app.user_role_assignment_removals WHERE assignment_id=%s", first),
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                (parameters,),
                APPEND_ONLY,
            )
        for query in (
            "TRUNCATE app.user_role_assignments CASCADE",
            "TRUNCATE app.user_role_assignment_removals",
        ):
            refused(connection, psycopg.errors.IntegrityConstraintViolation, query, (), APPEND_ONLY)
        assert connection.execute(
            "SELECT assignment.assignment_id,removal.reason FROM app.user_role_assignments "
            "AS assignment LEFT JOIN app.user_role_assignment_removals AS removal "
            "USING (assignment_id) WHERE assignment.actor_id=%s ORDER BY removal.reason",
            (actor_id,),
        ).fetchall() == [(first, "Moved to another desk"), (second, None)]
        connection.rollback()


def test_two_assignments_of_one_bundle_at_the_same_time_wait_and_one_is_refused(
    migrated_database_url: str,
) -> None:
    """Both at READ COMMITTED: the second waits for the first's lock and only then checks, so
    it sees the first's committed assignment; any other isolation level is refused (fail
    closed, as in sub-slice L1a). The Staff account, its bundle and the first assignment are
    committed."""
    with psycopg.connect(migrated_database_url) as setup:
        property_id = the_property(setup)
        actor_id = add_account(setup)
        bundle_id = add_bundle(setup, property_id, ("leases.read",))
        setup.commit()
    for isolation in (
        psycopg.IsolationLevel.REPEATABLE_READ,
        psycopg.IsolationLevel.SERIALIZABLE,
    ):
        with psycopg.connect(migrated_database_url) as other:
            other.isolation_level = isolation
            refused(
                other,
                psycopg.errors.ObjectNotInPrerequisiteState,
                ASSIGN,
                (uuid.uuid4(), actor_id, bundle_id, property_id),
                "a role bundle is assigned only at READ COMMITTED",
            )
            other.rollback()
    with (
        psycopg.connect(migrated_database_url) as first,
        # Review round 3: a lock timeout, so a wait that never ends fails instead of hanging.
        psycopg.connect(migrated_database_url, options="-c lock_timeout=15s") as second,
    ):
        assign(first, actor_id, bundle_id, property_id)
        # Review round 1: the second insert waits on the advisory lock while the first is
        # uncommitted, and is refused once the first commits (a check before the lock would
        # let both in).
        errors: list[BaseException] = []

        def second_assignment() -> None:
            try:
                assign(second, actor_id, bundle_id, property_id)
            except psycopg.Error as error:
                errors.append(error)

        waiter = threading.Thread(target=second_assignment)
        waiter.start()
        try:
            with psycopg.connect(migrated_database_url, autocommit=True) as watcher:
                deadline = time.monotonic() + 5
                while watcher.execute(
                    "SELECT wait_event_type,wait_event FROM pg_catalog.pg_stat_activity "
                    "WHERE pid=%s",
                    (second.info.backend_pid,),
                ).fetchone() != ("Lock", "advisory"):
                    assert time.monotonic() < deadline, "the second assignment never waited"
                    time.sleep(0.05)
            first.commit()
        finally:
            # Review round 3: release the first's lock before waiting for the thread, so a
            # failed wait check ends the test instead of hanging it.
            first.rollback()
            waiter.join(timeout=20)
        assert not waiter.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], psycopg.errors.UniqueViolation)
        assert ALREADY_ASSIGNED in str(errors[0])
        second.rollback()


def test_the_grant_reader_gives_an_active_classified_account_its_current_capabilities(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        staff = add_account(connection)
        desk = add_bundle(connection, property_id, ("leases.read", "payments.record"))
        reads = add_bundle(connection, property_id, ("leases.read", "customers.read"))
        assign(connection, staff, desk, property_id)
        reads_assignment = assign(connection, staff, reads, property_id)
        assert grants(connection, staff) == {
            ("leases.read", property_id),
            ("payments.record", property_id),
            ("customers.read", property_id),
        }
        reader = PostgresCapabilityGrantReader(cast(GrantConnection, connection))
        assert reader.grants_for(staff) == frozenset(
            CapabilityGrant(capability, frozenset({str(property_id)}))
            for capability in ("leases.read", "payments.record", "customers.read")
        )
        # A new version without a capability takes it away at the next read.
        next_version(connection, desk, ("leases.read",))
        connection.execute(REMOVE, (reads_assignment, "Reads no longer needed"))
        assert grants(connection, staff) == {("leases.read", property_id)}
        # A version with no capability at all gives nothing.
        next_version(connection, desk, ())
        assert grants(connection, staff) == set()
        for account_class, lifecycle in ((None, "active"), ("staff", "disabled")):
            account = add_account(connection, account_class, lifecycle)
            assign(connection, account, reads, property_id)
            assert grants(connection, account) == set()
        assert grants(connection, uuid.uuid4()) == set()
        # Review round 1: a disabled Owner gets nothing, also with a bundle (rolled back first,
        # because at most one Owner exists).
        with connection.transaction(force_rollback=True):
            disabled_owner = add_account(connection, "owner", "disabled")
            assign(connection, disabled_owner, reads, property_id)
            assert grants(connection, disabled_owner) == set()
        # Q-2026-10-21-162 (b): the Owner account class alone gives `identity.manage_access`.
        owner = add_account(connection, "owner")
        every_property = {
            row[0] for row in connection.execute("SELECT id FROM app.properties").fetchall()
        }
        assert grants(connection, owner) == {
            ("identity.manage_access", found) for found in every_property
        }
        # Review round 1: an Owner with a bundle gets the bundle's capabilities as well.
        assign(connection, owner, reads, property_id)
        assert grants(connection, owner) == {
            ("identity.manage_access", found) for found in every_property
        } | {("leases.read", property_id), ("customers.read", property_id)}
        manager = add_account(connection, "manager")
        assign(connection, manager, reads, property_id)
        assert grants(connection, manager) == {
            ("leases.read", property_id),
            ("customers.read", property_id),
        }
        connection.rollback()


def test_the_runtime_role_reads_grants_only_through_the_reader(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        property_id = the_property(setup)
        staff = add_account(setup)
        bundle_id = add_bundle(setup, property_id, ("units.read", "property.read"))
        assign(setup, staff, bundle_id, property_id)
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        reader = PostgresCapabilityGrantReader(cast(GrantConnection, runtime))
        assert reader.grants_for(staff) == frozenset(
            CapabilityGrant(capability, frozenset({str(property_id)}))
            for capability in ("units.read", "property.read")
        )
        for table in TABLES:
            refused(runtime, psycopg.errors.InsufficientPrivilege, f"SELECT 1 FROM {table}")
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            ASSIGN,
            (uuid.uuid4(), staff, bundle_id, property_id),
        )
        runtime.rollback()


def test_the_role_bundle_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Five relations (with their keys and one index), six trigger functions (not definers, no
    EXECUTE for the application roles), fifteen triggers and the definer grant reader are added;
    no existing function, trigger, relation, constraint or column changes; the runtime role may
    only execute the reader; forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> dict[str, set[str]]:
        with psycopg.connect(database) as connection:

            def rows(query: str) -> set[str]:
                return {
                    ":".join(str(item) for item in found)
                    for found in connection.execute(query).fetchall()
                }

            present = connection.execute("SELECT to_regclass('app.role_bundles')").fetchone()
            privileges = (
                rows(
                    "SELECT role,table_name,"
                    "has_table_privilege(role,table_name,'SELECT'),"
                    "has_table_privilege(role,table_name,"
                    "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
                    "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap',"
                    "'prm_backup','prm_restore','prm_human_admin']) role, "
                    f"unnest(ARRAY{list(TABLES)}) table_name"
                )
                | rows(
                    "SELECT role,function_name,"
                    "has_function_privilege(role,function_name,'EXECUTE') "
                    "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap',"
                    "'prm_backup','prm_restore','prm_human_admin']) role, "
                    f"unnest(ARRAY{sorted({*TRIGGER_FUNCTIONS, READER})}) function_name"
                )
                if present != (None,)
                else set()
            )
            return {
                "functions": rows(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ),
                "triggers": rows(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text,"
                    "pg_catalog.pg_get_triggerdef(t.oid) FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ),
                "relations": rows(
                    "SELECT c.oid::regclass::text,c.relkind,c.relacl::text "
                    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='app'"
                ),
                "constraints": rows(
                    "SELECT con.conrelid::regclass::text,con.conname,"
                    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace "
                    "WHERE n.nspname='app'"
                ),
                "columns": rows(
                    "SELECT a.attrelid::regclass::text,a.attname,"
                    "pg_catalog.format_type(a.atttypid,a.atttypmod),a.attacl::text "
                    "FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c "
                    "ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind='r' "
                    "AND a.attnum>0 AND NOT a.attisdropped"
                ),
                "privileges": privileges,
            }

    with _temporary_migration_database("prm_role_bundles") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("functions", "triggers", "relations", "constraints", "columns"):
        assert before[key] <= after[key]
    added_functions = {
        item.split(":")[0]: item for item in after["functions"] - before["functions"]
    }
    assert set(added_functions) == {*TRIGGER_FUNCTIONS, READER}
    for function, item in added_functions.items():
        definer = "True" if function == READER else "False"
        assert item.endswith(f":{definer}:{{search_path=pg_catalog}}")
    assert {item.split(":")[1] for item in after["triggers"] - before["triggers"]} == {
        "role_bundles_reject_truncate",
        "role_bundles_are_never_deleted",
        "role_bundles_change_by_version",
        "role_bundles_record_version",
        "role_bundle_versions_are_append_only",
        "role_bundle_versions_reject_truncate",
        "role_bundle_versions_follow_their_bundle",
        "role_bundle_capabilities_are_append_only",
        "role_bundle_capabilities_reject_truncate",
        "role_bundle_capabilities_follow_their_version",
        "user_role_assignments_are_append_only",
        "user_role_assignments_reject_truncate",
        "user_role_assignments_single_active",
        "user_role_assignment_removals_are_append_only",
        "user_role_assignment_removals_reject_truncate",
    }
    assert {item.split(":")[0] for item in after["relations"] - before["relations"]} == {
        *TABLES,
        "app.role_bundles_pkey",
        "app.role_bundles_property_lower_name_key",
        "app.role_bundles_bundle_property_key",
        "app.role_bundle_versions_pkey",
        "app.role_bundle_capabilities_pkey",
        "app.user_role_assignments_pkey",
        "app.user_role_assignments_actor_idx",
        "app.user_role_assignment_removals_pkey",
    }
    for key in ("constraints", "columns"):
        assert {item.split(":")[0] for item in after[key] - before[key]} == set(TABLES)
    expected: set[str] = set()
    for role in (
        "prm_runtime",
        "prm_financial",
        "prm_bootstrap",
        "prm_backup",
        "prm_restore",
        "prm_human_admin",
    ):
        # The backup role reads every table through pg_read_all_data (scripts/postgres-init.sh).
        expected |= {f"{role}:{table}:{role == 'prm_backup'}:False" for table in TABLES}
        expected |= {f"{role}:{function}:False" for function in TRIGGER_FUNCTIONS}
        expected.add(f"{role}:{READER}:{role == 'prm_runtime'}")
    assert after["privileges"] == expected
