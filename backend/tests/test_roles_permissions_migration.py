"""Roles and permissions on the real database (migration 20270423_273, V1.1 part 3, DL-120).

The permissions list covers every capability a person can hold once; the default roles are whole
permissions with Khmer names; a role can be turned off only without users; "Change business
rules" is a role right with the DL-081 sign-in code rule; and the old per-user Settings access
becomes that role on upgrade.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from test_access_admin_flow_migration import allow_admin_actions, context, refused
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property
from test_settings_access_migration import add_sign_in_code

REVISION = "20270423_273"
GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"


@dataclass(frozen=True)
class RolesDatabase:
    owner_url: str
    runtime_url: str
    property_id: str
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    defaults: tuple[uuid.UUID, uuid.UUID, uuid.UUID]


@pytest.fixture(scope="module")
def roles_database(migrated_database_url: str) -> Iterator[RolesDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_roles_permissions") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            setup.commit()
        allow_admin_actions(temporary, owner, manager)
        yield RolesDatabase(
            temporary,
            runtime_url,
            str(property_id),
            owner,
            manager,
            staff,
            (uuid.UUID(str(seeded[0])), uuid.UUID(str(seeded[1])), uuid.UUID(str(seeded[2]))),
        )


def grants(database: RolesDatabase, actor: uuid.UUID) -> set[str]:
    with psycopg.connect(database.owner_url) as connection:
        return {str(row[0]) for row in connection.execute(GRANTS, (actor,)).fetchall()}


def test_migration_273_follows_the_reservation_rules() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    found = scripts.get_revision(REVISION)
    assert found is not None and found.down_revision == "20270422_272"
    with pytest.raises(RuntimeError, match="forward-only"):
        found.module.downgrade()


def test_every_capability_a_person_holds_is_in_exactly_one_permission(
    roles_database: RolesDatabase,
) -> None:
    with psycopg.connect(roles_database.owner_url) as connection:
        unlisted = connection.execute(
            "SELECT capability_id FROM app.capabilities WHERE grant_path <> 'service_principal' "
            "EXCEPT SELECT capability_id FROM app.permission_capabilities"
        ).fetchall()
        assert unlisted == []
        rows = connection.execute(
            "SELECT permission_code, group_code, capability_ids FROM app.permission_catalog()"
        ).fetchall()
        listed = [name for row in rows for name in row[2]]
        assert len(listed) == len(set(listed))
        assert [row[1] for row in rows if row[0] == "BASIC"] == [None]
        assert all(row[1] is not None for row in rows if row[0] != "BASIC")
        assert {"settings.manage", "identity.manage_access"} <= set(listed)
        assert "rent_nonpayment.evaluate" not in listed
        for change in (
            "UPDATE app.permissions SET name_en = 'x' WHERE permission_code = 'RULES'",
            "DELETE FROM app.permission_capabilities WHERE capability_id = 'ledger.read'",
        ):
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                connection.execute(change)
            connection.rollback()


def test_the_default_roles_are_whole_permissions_with_khmer_names(
    roles_database: RolesDatabase,
) -> None:
    database = roles_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    found = flow.roles_and_permissions(
        property_id=database.property_id, actor_id=str(database.owner), request_id="r"
    )
    by_id = {role.role_bundle_id: role for role in found.roles}
    owner_role, manager_role, staff_role = (by_id[bundle] for bundle in database.defaults)
    assert (owner_role.name_kh, manager_role.name_kh, staff_role.name_kh) == (
        "ម្ចាស់",
        "អ្នកគ្រប់គ្រង",
        "បុគ្គលិក",
    )
    assert owner_role.owner_role and not manager_role.owner_role
    assert "settings.manage" in owner_role.capability_ids
    assert "settings.manage" not in manager_role.capability_ids
    for role in (owner_role, manager_role, staff_role):
        held = set(role.capability_ids)
        for permission in found.permissions:
            given = set(permission.capability_ids) & held
            if permission.permission_code == "USERS":
                assert not given
            else:
                assert given in (set(), set(permission.capability_ids)), (
                    role.name,
                    permission.permission_code,
                )
    assert found.permissions[0].permission_code == "BASIC" and set(
        found.permissions[0].capability_ids
    ) <= set(staff_role.capability_ids)


def test_change_business_rules_is_a_role_right_with_the_sign_in_code_rule(
    roles_database: RolesDatabase,
) -> None:
    database = roles_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    role = flow.save_role(
        property_id=database.property_id,
        role_bundle_id=None,
        expected_version=None,
        name=f"Rules {uuid.uuid4().hex[:6]}",
        name_kh="ច្បាប់",
        capability_ids=("settings.manage", "ledger.read"),
        turned_off=False,
        audit_context=context(database.owner),
    )
    assert role.version == 1 and role.holders == 0
    assert {"settings.manage", "ledger.read", "units.read", "identity.read_self"} <= set(
        role.capability_ids
    )
    refused(
        "SIGN_IN_CODE_REQUIRED",
        409,
        flow.assign_role_bundle,
        user_id=database.staff,
        role_bundle_id=role.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    flow.assign_role_bundle(
        user_id=database.manager,
        role_bundle_id=role.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    assert {"settings.manage", "ledger.read"} <= grants(database, database.manager)
    with psycopg.connect(database.owner_url) as connection:
        add_sign_in_code(connection, database.staff)
        connection.commit()
    flow.assign_role_bundle(
        user_id=database.staff,
        role_bundle_id=role.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    assert "settings.manage" in grants(database, database.staff)
    # The code reset: the right stops working (DL-081), the role stays.
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET mfa_policy_class='optional' WHERE actor_id=%s",
            (database.staff,),
        )
        connection.commit()
    assert "settings.manage" not in grants(database, database.staff)
    assert "ledger.read" in grants(database, database.staff)
    # A role with users is not turned off; taking the right away keeps the other rights.
    refused(
        "ROLE_HAS_USERS",
        409,
        flow.save_role,
        property_id=database.property_id,
        role_bundle_id=role.role_bundle_id,
        expected_version=1,
        name=role.name,
        name_kh=role.name_kh,
        capability_ids=("ledger.read",),
        turned_off=True,
        audit_context=context(database.owner),
    )
    saved = flow.save_role(
        property_id=database.property_id,
        role_bundle_id=role.role_bundle_id,
        expected_version=1,
        name=role.name,
        name_kh=role.name_kh,
        capability_ids=("ledger.read",),
        turned_off=False,
        audit_context=context(database.owner),
    )
    assert saved.version == 2 and saved.holders == 2
    assert "settings.manage" not in saved.capability_ids
    assert "settings.manage" not in grants(database, database.manager)
    assert "ledger.read" in grants(database, database.manager)


def test_a_turned_off_role_gives_nothing_and_cannot_be_given(
    roles_database: RolesDatabase,
) -> None:
    database = roles_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    role = flow.save_role(
        property_id=database.property_id,
        role_bundle_id=None,
        expected_version=None,
        name=f"Night desk {uuid.uuid4().hex[:6]}",
        name_kh=None,
        capability_ids=("ledger.close",),
        turned_off=False,
        audit_context=context(database.owner),
    )
    off = flow.save_role(
        property_id=database.property_id,
        role_bundle_id=role.role_bundle_id,
        expected_version=1,
        name=role.name,
        name_kh=None,
        capability_ids=("ledger.close",),
        turned_off=True,
        audit_context=context(database.owner),
    )
    assert off.turned_off and off.version == 2
    refused(
        "ROLE_TURNED_OFF",
        409,
        flow.assign_role_bundle,
        user_id=database.manager,
        role_bundle_id=role.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    refused(
        "STALE_VERSION",
        412,
        flow.save_role,
        property_id=database.property_id,
        role_bundle_id=role.role_bundle_id,
        expected_version=1,
        name=role.name,
        name_kh=None,
        capability_ids=("ledger.close",),
        turned_off=False,
        audit_context=context(database.owner),
    )
    with psycopg.connect(database.owner_url) as connection:
        # Even a row written past the screen gives nothing while the role is off.
        connection.execute(
            "INSERT INTO app.user_role_assignments (assignment_id, actor_id, role_bundle_id, "
            "property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
            (uuid.uuid4(), database.manager, role.role_bundle_id, database.property_id),
        )
        connection.commit()
    assert role.role_bundle_id in {
        assignment.role_bundle_id
        for assignment in flow.roles_and_permissions(
            property_id=database.property_id, actor_id=str(database.owner), request_id="r"
        ).assignments
    }
    # The Manager role has no ledger.close (the Owner's own ledger work).
    assert "ledger.close" not in grants(database, database.manager)


def test_the_owner_role_is_locked_and_only_for_the_owner(roles_database: RolesDatabase) -> None:
    database = roles_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    owner_role = next(
        role
        for role in flow.roles_and_permissions(
            property_id=database.property_id, actor_id=str(database.owner), request_id="r"
        ).roles
        if role.owner_role
    )
    for name, turned_off in (("Boss", False), (owner_role.name, True)):
        refused(
            "OWNER_ROLE_LOCKED",
            403,
            flow.save_role,
            property_id=database.property_id,
            role_bundle_id=owner_role.role_bundle_id,
            expected_version=owner_role.version,
            name=name,
            name_kh=owner_role.name_kh,
            capability_ids=owner_role.capability_ids,
            turned_off=turned_off,
            audit_context=context(database.owner),
        )
    # One Owner: the Owner role is not given to anyone else, and the Owner keeps it.
    refused(
        "OWNER_ROLE_LOCKED",
        403,
        flow.assign_role_bundle,
        user_id=database.manager,
        role_bundle_id=owner_role.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    if owner_role.holders == 0:
        flow.assign_role_bundle(
            user_id=database.owner,
            role_bundle_id=owner_role.role_bundle_id,
            property_id=database.property_id,
            audit_context=context(database.owner),
        )
    refused(
        "OWNER_ROLE_LOCKED",
        403,
        flow.remove_role_assignment,
        user_id=database.owner,
        role_bundle_id=owner_role.role_bundle_id,
        property_id=database.property_id,
        reason="Try to lock myself out",
        audit_context=context(database.owner),
    )
    refused(
        "FORBIDDEN",
        403,
        flow.save_role,
        property_id=database.property_id,
        role_bundle_id=None,
        expected_version=None,
        name="Not the Owner",
        name_kh=None,
        capability_ids=(),
        turned_off=False,
        audit_context=context(database.manager),
    )


def test_the_old_settings_access_becomes_the_change_business_rules_role(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("prm_roles_upgrade") as temporary:
        assert _run_alembic("upgrade", "20270422_272").returncode == 0
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            setup.execute(SEED_QUERY, (property_id,))
            given: Any = setup.execute(
                "SELECT app.give_settings_access(%s, %s, %s)",
                (owner, manager, "Changes the Water Rate"),
            ).fetchone()
            setup.commit()
        assert _run_alembic("upgrade", "head").returncode == 0
        with psycopg.connect(temporary) as connection:
            removed = connection.execute(
                "SELECT reason FROM app.user_capability_grant_removals WHERE grant_id = %s",
                (given[0],),
            ).fetchone()
            assert removed is not None and "Change business rules" in str(removed[0])
            role = connection.execute(
                "SELECT bundle.name, bundle.name_kh, bundle.settings_access "
                "FROM app.user_role_assignments AS assignment "
                "JOIN app.role_bundles AS bundle USING (role_bundle_id) "
                "WHERE assignment.actor_id = %s AND bundle.settings_access",
                (manager,),
            ).fetchall()
            assert role == [("Change business rules", "ប្ដូរច្បាប់អាជីវកម្ម", True)]
            held = {str(row[0]) for row in connection.execute(GRANTS, (manager,)).fetchall()}
            assert "settings.manage" in held
