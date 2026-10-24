"""Hidden characters in names (login slice sub-slice L2c).

DL-081 (Q-2026-10-22-169 (a)), DB-AUTH-007, DB-AUTH-010, API-079, API-080: the API removes U+200B
from a name before saving it; the database refuses every other hidden character of
`property_rental.visible_text.HIDDEN_NAME_CHARACTERS`, a space other than U+0020, two spaces in
a row and a name that is not NFC, in an account name and a role bundle name. The flow tests use
one throwaway database at head, shared by this module.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_admin_api import AccessAdministrationRejected
from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from property_rental.visible_text import HIDDEN_NAME_CHARACTERS, SPACE_SEPARATORS
from test_access_admin_flow_migration import AdminDatabase, allow_admin_actions, context
from test_account_class_migration import repository_for
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import ADD_ACCOUNT, add_account, the_property

REVISION = "20270126_183"
PREVIOUS = "20270125_182"
SOKHA = "\u179f\u17bb\u1781\u17b6"
CHAN = "\u1785\u17b6\u1793\u17cb"
NEWLY_REFUSED = (
    "\u034f",
    "\u115f",
    "\u1160",
    "\u17b4",
    "\u17b5",
    "\u180b",
    "\u2028",
    "\u2029",
    "\u2800",
    "\u3164",
    "\ufe0f",
    "\uffa0",
    "\ufff0",
    "\U0001bca0",
    "\U0001d173",
    "\U000e0100",
)
# Neighbours of the refused characters that a name may hold.
ACCEPTED = (
    "\u00ac",
    "\u00ae",
    "\u034e",
    "\u0350",
    "\u061b",
    "\u061d",
    "\u115e",
    "\u1161",
    "\u17b3",
    "\u17b6",
    "\u180a",
    "\u1810",
    "\u2027",
    "\u2030",
    "\u2070",
    "\u27ff",
    "\u2801",
    "\u3163",
    "\u3165",
    "\ufdfd",
    "\ufe10",
    "\ufefe",
    "\uff9f",
    "\uffa1",
    "\uffee",
    "\ufffc",
    "\U0001bc9c",
    "\U0001d172",
    "\U0001d17b",
)
# The code points the exact comparison tries: the Basic Multilingual Plane without the
# surrogates, the two blocks of U+1BCA0 and U+1D173, and U+E0000 to U+E0FFF.
CANDIDATES = [
    point
    for point in (
        *range(1, 0x10000),
        *range(0x1BC00, 0x1BD00),
        *range(0x1D100, 0x1D200),
        *range(0xE0000, 0xE1000),
    )
    if not 0xD800 <= point <= 0xDFFF
]
REFUSED_ACCOUNT_NAMES = """
    CREATE FUNCTION pg_temp.refused_account_names(p_points integer[])
    RETURNS SETOF integer
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_point integer;
    BEGIN
        FOREACH v_point IN ARRAY p_points LOOP
            BEGIN
                PERFORM app.assert_account_names(ARRAY['A' || chr(v_point) || 'B']);
            EXCEPTION WHEN invalid_parameter_value THEN
                RETURN NEXT v_point;
            END;
        END LOOP;
    END;
    $$
"""
REFUSED_BUNDLE_NAMES = """
    CREATE FUNCTION pg_temp.refused_bundle_names(p_property uuid, p_points integer[])
    RETURNS SETOF integer
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_point integer;
    BEGIN
        FOREACH v_point IN ARRAY p_points LOOP
            BEGIN
                INSERT INTO app.role_bundles(role_bundle_id, property_id, name, version, provenance)
                VALUES (
                    gen_random_uuid(), p_property, 'A' || chr(v_point) || 'B ' || v_point, 1,
                    'login-slice-l2c-test'
                );
            EXCEPTION WHEN check_violation THEN
                RETURN NEXT v_point;
            END;
        END LOOP;
    END;
    $$
"""
ROLES = (
    "prm_runtime",
    "prm_financial",
    "prm_bootstrap",
    "prm_backup",
    "prm_restore",
    "prm_human_admin",
)


@pytest.fixture(scope="module")
def admin_database(migrated_database_url: str) -> Iterator[AdminDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_name_hidden_characters") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            setup.execute(SEED_QUERY, (property_id,))
            setup.commit()
        allow_admin_actions(temporary, owner, manager)
        yield AdminDatabase(temporary, runtime_url, str(property_id), owner, manager)


def refused(code: str, status: int, call: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(AccessAdministrationRejected) as caught:
        call(*args, **kwargs)
    assert (caught.value.status_code, caught.value.code) == (status, code)


def points(pattern_matches: Any) -> set[int]:
    return {point for point in CANDIDATES if pattern_matches(chr(point))}


def test_a_name_typed_with_a_khmer_keyboard_is_saved_without_its_zero_width_space(
    admin_database: AdminDatabase,
) -> None:
    """Owner's example (Q-2026-10-22-169 (a)): the Staff member "sokha chan", typed on an iPad
    whose keyboard puts U+200B after the first word, is saved and listed without it; a username
    and a bundle name lose it too, so a bundle name that differs from another only by U+200B is
    taken."""
    flow = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    suffix = uuid.uuid4().hex[:8]
    typed = f"{SOKHA}\u200b {CHAN}"
    created = flow.create_user(
        property_id=admin_database.property_id,
        username=f"\u200bsokha.chan-{suffix}\u200b",
        display_name=typed,
        audit_name=f"{typed} {suffix}",
        account_class="staff",
        audit_context=context(admin_database.owner),
    )
    assert (created.username, created.display_name, created.audit_name) == (
        f"sokha.chan-{suffix}",
        f"{SOKHA} {CHAN}",
        f"{SOKHA} {CHAN} {suffix}",
    )
    page, _ = flow.list_users(
        property_id=admin_database.property_id,
        cursor=None,
        limit=100,
        actor_id=str(admin_database.owner),
        request_id=str(uuid.uuid4()),
    )
    listed = next(account for account in page if account.user_id == created.user_id)
    assert listed.display_name == f"{SOKHA} {CHAN}"
    refused(
        "USERNAME_TAKEN",
        409,
        flow.create_user,
        property_id=admin_database.property_id,
        username=f"sokha.chan-\u200b{suffix}",
        display_name="Another Sokha",
        audit_name="Another Sokha",
        account_class="staff",
        audit_context=context(admin_database.owner),
    )

    bundle = flow.create_role_bundle(
        property_id=admin_database.property_id,
        name=f"Front\u200b desk {suffix}",
        capability_ids=(),
        audit_context=context(admin_database.owner),
    )
    assert bundle.name == f"Front desk {suffix}"
    refused(
        "ROLE_BUNDLE_NAME_TAKEN",
        409,
        flow.create_role_bundle,
        property_id=admin_database.property_id,
        name=f"Front desk\u200b {suffix}",
        capability_ids=(),
        audit_context=context(admin_database.owner),
    )
    joined = flow.create_role_bundle(
        property_id=admin_database.property_id,
        name=f"Back\u200bdesk {suffix}",
        capability_ids=(),
        audit_context=context(admin_database.owner),
    )
    assert joined.name == f"Backdesk {suffix}"
    # Review round 1: the update paths lose it too.
    changed = flow.update_user(
        user_id=created.user_id,
        property_id=admin_database.property_id,
        expected_version=created.version,
        display_name=f"{CHAN}\u200b {SOKHA}",
        audit_name=None,
        lifecycle_state=None,
        mfa_policy_class=None,
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(admin_database.owner),
    )
    assert changed.display_name == f"{CHAN} {SOKHA}"
    renamed = flow.update_role_bundle(
        role_bundle_id=joined.role_bundle_id,
        property_id=admin_database.property_id,
        expected_version=joined.version,
        name=f"Back\u200b desk {suffix}",
        capability_ids=None,
        revoke_affected_sessions_on_capability_reduction=True,
        audit_context=context(admin_database.owner),
    )
    assert renamed.name == f"Back desk {suffix}"


def test_a_name_typed_with_two_spaces_is_saved_tidied_and_found_at_sign_in(
    admin_database: AdminDatabase,
) -> None:
    """Owner's example (Q-2026-10-22-170 (a), login sub-slice L2d): Staff types "Sokha  Chan"
    with two spaces on the iPad; it is saved as "Sokha Chan" (username "sokha chan") and nobody
    sees an error; every spelling the sign-in lookup tidies finds that account on the database
    (review round 1: a real lookup; since L4 the account's own first one-time password is its
    credential row), and the same username typed with a no-break space is taken. The database
    still refuses two spaces in a row from a caller that skips the flow (tested below), so its
    rule stays the last guard."""
    flow = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    suffix = uuid.uuid4().hex[:8]
    created = flow.create_user(
        property_id=admin_database.property_id,
        username=f"Sokha  Chan {suffix}",
        display_name="Sokha  Chan",
        audit_name=f"\u00a0Sokha \u3000Chan {suffix} ",
        account_class="staff",
        audit_context=context(admin_database.owner),
    )
    assert (created.username, created.display_name, created.audit_name) == (
        f"sokha chan {suffix}",
        "Sokha Chan",
        f"Sokha Chan {suffix}",
    )
    with psycopg.connect(admin_database.owner_url) as connection:
        stored = connection.execute(
            "SELECT normalized_username FROM app.user_accounts WHERE actor_id = %s",
            (created.user_id,),
        ).fetchone()
        # Login sub-slice L4: the account already has a credential, its first one-time password.
    assert stored == (f"sokha chan {suffix}",)
    with psycopg.connect(admin_database.runtime_url) as runtime:
        repository = repository_for(runtime)
        for typed in (
            f"Sokha  Chan {suffix}",
            f" SOKHA\u00a0Chan\u2009 {suffix} ",
            f"sokha\u3000chan {suffix}",
        ):
            found = repository.find_by_username(typed)
            assert found is not None and found.actor_id == str(created.user_id), typed
        assert repository.find_by_username(f"sokha\tchan {suffix}") is None
    refused(
        "USERNAME_TAKEN",
        409,
        flow.create_user,
        property_id=admin_database.property_id,
        username=f"sokha\u00a0chan {suffix}",
        display_name="Another Sokha",
        audit_name="Another Sokha",
        account_class="staff",
        audit_context=context(admin_database.owner),
    )
    changed = flow.update_user(
        user_id=created.user_id,
        property_id=admin_database.property_id,
        expected_version=created.version,
        display_name="Chan\u202f\u202fSokha ",
        audit_name=None,
        lifecycle_state=None,
        mfa_policy_class=None,
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(admin_database.owner),
    )
    assert changed.display_name == "Chan Sokha"
    bundle = flow.create_role_bundle(
        property_id=admin_database.property_id,
        name=f"Front  desk\u3000{suffix}",
        capability_ids=(),
        audit_context=context(admin_database.owner),
    )
    assert bundle.name == f"Front desk {suffix}"


def test_the_flow_refuses_the_remaining_hidden_characters_in_names(
    admin_database: AdminDatabase,
) -> None:
    """Q-2026-10-22-169 (a) gap (2): U+034F, the Hangul fillers, the invisible Khmer vowels and
    the line and paragraph separators inside a name are refused, for accounts and bundles."""
    flow = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    staff = flow.create_user(
        property_id=admin_database.property_id,
        username=f"hidden-{uuid.uuid4().hex[:8]}",
        display_name="Hidden Test",
        audit_name="Hidden Test",
        account_class="staff",
        audit_context=context(admin_database.owner),
    )
    for character in NEWLY_REFUSED:
        name = f"Dara{character}Sok"
        refused(
            "INVALID_NAME",
            422,
            flow.create_user,
            property_id=admin_database.property_id,
            username=f"hidden-{uuid.uuid4().hex[:8]}",
            display_name=name,
            audit_name="Hidden",
            account_class="staff",
            audit_context=context(admin_database.owner),
        )
        refused(
            "INVALID_NAME",
            422,
            flow.update_user,
            user_id=staff.user_id,
            property_id=admin_database.property_id,
            expected_version=staff.version,
            display_name=None,
            audit_name=name,
            lifecycle_state=None,
            mfa_policy_class=None,
            revoke_applicable_sessions_if_disabled=True,
            audit_context=context(admin_database.owner),
        )
        refused(
            "INVALID_NAME",
            422,
            flow.create_role_bundle,
            property_id=admin_database.property_id,
            name=f"Night{character}desk",
            capability_ids=(),
            audit_context=context(admin_database.owner),
        )
    # Review round 2: a rename meets the new bundle check on UPDATE.
    bundle = flow.create_role_bundle(
        property_id=admin_database.property_id,
        name=f"Night desk {uuid.uuid4().hex[:8]}",
        capability_ids=(),
        audit_context=context(admin_database.owner),
    )
    refused(
        "INVALID_NAME",
        422,
        flow.update_role_bundle,
        role_bundle_id=bundle.role_bundle_id,
        property_id=admin_database.property_id,
        expected_version=bundle.version,
        name="Night\u2800desk",
        capability_ids=None,
        revoke_affected_sessions_on_capability_reduction=True,
        audit_context=context(admin_database.owner),
    )


def test_the_database_refuses_every_hidden_character_and_a_name_that_is_not_nfc(
    admin_database: AdminDatabase,
) -> None:
    """For every candidate code point (review round 1), the account name check and the two
    bundle name checks refuse exactly the characters of `HIDDEN_NAME_CHARACTERS`, the spaces
    other than U+0020 that the API folds, and the characters that make the name not NFC, so the
    database and application lists stay in step; two spaces in a row and a decomposed name are
    refused, an NFC name is accepted. The compose database runs the glibc `en_US.utf8` locale,
    whose `[[:cntrl:]]` adds only U+2028 and U+2029, which are in the list."""
    hidden = points(HIDDEN_NAME_CHARACTERS.fullmatch)
    other_spaces = points(SPACE_SEPARATORS.fullmatch) - {ord(" ")}
    assert {ord(character) for character in NEWLY_REFUSED} <= hidden
    assert not {ord(character) for character in ACCEPTED} & (hidden | other_spaces)

    with psycopg.connect(admin_database.owner_url) as connection:
        # Review round 2: under an ICU locale `[[:cntrl:]]` also refuses the format characters,
        # so the exact comparison holds only for the libc provider the compose database uses.
        provider = connection.execute(
            "SELECT datlocprovider FROM pg_catalog.pg_database WHERE datname = current_database()"
        ).fetchone()
        assert provider == ("c",), f"the exact comparison needs the libc locale, got {provider}"
        property_id = the_property(connection)
        connection.execute(REFUSED_ACCOUNT_NAMES)
        connection.execute(REFUSED_BUNDLE_NAMES)
        not_nfc = {
            int(row[0])
            for row in connection.execute(
                "SELECT point FROM unnest(%s::integer[]) AS point "
                "WHERE ('A' || chr(point) || 'B') IS NOT NFC NORMALIZED",
                (CANDIDATES,),
            ).fetchall()
        }
        expected = hidden | other_spaces | not_nfc
        refused_accounts = {
            int(row[0])
            for row in connection.execute(
                "SELECT pg_temp.refused_account_names(%s)", (CANDIDATES,)
            ).fetchall()
        }
        refused_bundles = {
            int(row[0])
            for row in connection.execute(
                "SELECT pg_temp.refused_bundle_names(%s, %s)", (property_id, CANDIDATES)
            ).fetchall()
        }
        assert refused_accounts == expected, sorted(refused_accounts ^ expected)[:20]
        assert refused_bundles == expected, sorted(refused_bundles ^ expected)[:20]
        assert not {ord(character) for character in ACCEPTED} & refused_accounts
        assert ord("\u0301") in not_nfc

        def account_name_refused(name: str) -> bool:
            try:
                with connection.transaction():
                    connection.execute("SELECT app.assert_account_names(%s)", ([name],))
            except psycopg.errors.InvalidParameterValue:
                return True
            return False

        assert account_name_refused("Front  desk")
        assert account_name_refused("Cafe\u0301 desk")
        assert not account_name_refused("Caf\u00e9 desk")
        connection.rollback()


@pytest.mark.parametrize("username", ["cafe\u0301.desk", "dara\u200b.sok"])
def test_the_migration_refuses_to_run_over_a_username_that_is_not_nfc(
    migrated_database_url: str,
    username: str,
) -> None:
    """Review round 1 (security): the sign-in lookup now makes a typed username NFC, so the
    upgrade refuses to run while a stored username is not NFC (or holds U+200B) instead of
    leaving an account that can never sign in; nothing is changed."""
    assert migrated_database_url
    with _temporary_migration_database("prm_name_hidden_characters_guard") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        with psycopg.connect(temporary) as setup:
            setup.execute(ADD_ACCOUNT, (uuid.uuid4(), username, "active", "optional"))
        result = _run_alembic("upgrade", REVISION)
        assert result.returncode != 0
        assert "a stored username is not NFC or holds U+200B" in result.stderr
        with psycopg.connect(temporary) as check:
            assert check.execute("SELECT version_num FROM alembic_version").fetchone() == (
                PREVIOUS,
            )


def test_the_name_hidden_characters_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the body of `app.assert_account_names` changes and one check constraint is added to
    `app.role_bundles`; no privilege, relation, trigger or column changes; forward-only."""
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

            return {
                "functions": rows(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proowner,p.provolatile,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ),
                "attributes": rows(
                    "SELECT p.oid::regprocedure::text,p.proowner,p.provolatile,p.prosecdef,"
                    "p.proconfig::text,p.proparallel,p.proisstrict,p.proleakproof,"
                    "p.prorettype::regtype::text FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='app' AND p.prokind='f'"
                ),
                "acls": rows(
                    "SELECT p.oid::regprocedure::text,p.proacl::text "
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
                "privileges": rows(
                    "SELECT role,has_function_privilege(role,"
                    "'app.assert_account_names(text[])','EXECUTE') "
                    f"FROM unnest(ARRAY{list(ROLES)}) role"
                ),
            }

    with _temporary_migration_database("prm_name_hidden_characters_catalog") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("attributes", "acls", "triggers", "relations", "columns", "privileges"):
        assert before[key] == after[key], key
    assert {item for item in after["privileges"] if item.endswith(":True")} == set()

    def by_name(items: set[str]) -> dict[str, str]:
        return {item.split(":")[0]: item for item in items}

    old, new = by_name(before["functions"]), by_name(after["functions"])
    assert set(old) == set(new)
    assert {name for name in old if old[name] != new[name]} == {"app.assert_account_names(text[])"}
    assert "IS NOT NFC NORMALIZED" in new["app.assert_account_names(text[])"]
    added = after["constraints"] - before["constraints"]
    assert before["constraints"] - after["constraints"] == set()
    assert len(added) == 1
    (constraint,) = added
    assert constraint.startswith("app.role_bundles:role_bundles_name_visible_check:CHECK")
    assert "IS NFC NORMALIZED" in constraint
