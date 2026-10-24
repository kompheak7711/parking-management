"""Login sub-slice L3a-2 review round 1: a session revocation time is never before its last
activity (migration `20270127_184`; DL-057, DB-AUTH-004, SEC-017).

One throwaway database at head with the default bundles seeded. A sign-out and an Owner's
revocation each meet an activity that a parallel request committed after the revocation's
statement started; both now succeed and record the activity's time.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from property_rental.auth_flow import PostgresAuthenticationFlow
from test_access_admin_flow_migration import allow_admin_actions, context
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

REVISION = "20270127_184"
PREVIOUS = "20270126_183"
PASSWORD = "correct horse battery staple"
SESSION_OF = (
    "SELECT revoked_at, last_activity_at, revocation_reason FROM app.browser_sessions "
    "WHERE token_verifier = %s"
)
FUNCTION_FACTS = """
    SELECT pg_catalog.pg_get_userbyid(proc.proowner), proc.prosecdef, proc.proconfig,
           proc.proacl::text, proc.provolatile, proc.prorettype::regtype::text, proc.prolang
    FROM pg_catalog.pg_proc AS proc
    WHERE proc.oid = 'app.protect_browser_session_lifecycle()'::regprocedure
"""


@dataclass(frozen=True)
class RevocationDatabase:
    owner_url: str
    runtime_url: str
    property_id: str
    owner: uuid.UUID


@pytest.fixture(scope="module")
def revocation_database(migrated_database_url: str) -> Iterator[RevocationDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_session_revocation_time") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            setup.execute(SEED_QUERY, (property_id,))
            setup.commit()
        allow_admin_actions(temporary, owner)
        yield RevocationDatabase(temporary, runtime_url, str(property_id), owner)


def signed_in_staff(database: RevocationDatabase, username: str) -> tuple[uuid.UUID, str]:
    created = PostgresAccessAdministrationFlow(database.runtime_url).create_user(
        property_id=database.property_id,
        username=username,
        display_name=username,
        audit_name=username,
        account_class="staff",
        audit_context=context(database.owner),
    )
    # Login sub-slice L4: a new account's first password is a one-time password, changed at the
    # first sign-in; the account then signs in with its own password.
    flow = PostgresAuthenticationFlow(database.runtime_url)
    assert created.one_time_password is not None
    started = flow.login(
        username=username,
        password=created.one_time_password.value,
        request_source="desk",
        request_id="l3a-2",
    )
    assert started.preauth_token is not None
    flow.change_password(
        preauth_token=started.preauth_token, new_password=PASSWORD, request_id="l3a-2"
    )
    result = flow.login(
        username=username, password=PASSWORD, request_source="desk", request_id="l3a-2"
    )
    assert result.session_token is not None
    return created.user_id, result.session_token


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def revoke_while_a_later_activity_commits(
    database: RevocationDatabase, token: str, revoke: Callable[[], Any]
) -> None:
    """Hold the session row, start the revocation (it waits for the row), then record an
    activity whose time is after the revocation statement started and let both finish."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            revoke()
        except BaseException as exc:  # the test reports any failure of the revocation
            errors.append(exc)

    with psycopg.connect(database.owner_url, autocommit=False) as holder:
        holder.execute(
            "SELECT 1 FROM app.browser_sessions WHERE token_verifier = %s FOR UPDATE",
            (digest(token),),
        )
        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.monotonic() + 20
        with psycopg.connect(database.owner_url, autocommit=True) as watcher:
            while True:
                # `pg_locks` shows every role's locks (`pg_stat_activity` hides another role's
                # wait from a role that is not a superuser); a wait for a row is a wait for the
                # holder's transaction id, a lock that belongs to no database.
                waiting = watcher.execute(
                    "SELECT count(*) FROM pg_catalog.pg_locks AS waiting_lock "
                    "WHERE NOT waiting_lock.granted AND (waiting_lock.database IS NULL "
                    "OR waiting_lock.database = (SELECT oid FROM pg_catalog.pg_database "
                    "WHERE datname = current_database()))"
                ).fetchone()
                if waiting is not None and waiting[0] >= 1:
                    break
                assert worker.is_alive(), f"the revocation ended without waiting: {errors}"
                assert time.monotonic() < deadline, "the revocation never waited for the row"
                time.sleep(0.05)
        holder.execute(
            "UPDATE app.browser_sessions SET last_activity_at = statement_timestamp() "
            "WHERE token_verifier = %s",
            (digest(token),),
        )
        holder.commit()
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert errors == []


def test_a_sign_out_that_meets_a_later_activity_records_the_activity_time(
    revocation_database: RevocationDatabase,
) -> None:
    """A sign-out whose statement started before a parallel activity committed revokes the
    session; the revocation time is the activity's time, never before it."""
    _, token = signed_in_staff(revocation_database, "l3a-2.race-out")
    flow = PostgresAuthenticationFlow(revocation_database.runtime_url)
    revoke_while_a_later_activity_commits(
        revocation_database,
        token,
        lambda: flow.logout(session_token=token, request_id="l3a-2-race"),
    )
    with psycopg.connect(revocation_database.owner_url) as connection:
        row = connection.execute(SESSION_OF, (digest(token),)).fetchone()
    assert row is not None
    revoked_at, last_activity_at, reason = row
    # Review round 2: equal, not only later, which shows that the activity committed after the
    # revocation statement started (otherwise the statement time would be later).
    assert reason == "logout" and revoked_at == last_activity_at


def test_an_owner_revocation_that_meets_a_later_activity_still_ends_the_session(
    revocation_database: RevocationDatabase,
) -> None:
    """SEC-017: the Owner's revocation of an account's sessions, whose statement started before
    the person's own request committed an activity, still ends the session (before migration
    `20270127_184` it rolled back with a check violation)."""
    staff, token = signed_in_staff(revocation_database, "l3a-2.race-owner")
    admin = PostgresAccessAdministrationFlow(revocation_database.runtime_url)
    revoke_while_a_later_activity_commits(
        revocation_database,
        token,
        lambda: admin.revoke_user_sessions(
            user_id=staff, audit_context=context(revocation_database.owner)
        ),
    )
    with psycopg.connect(revocation_database.owner_url) as connection:
        row = connection.execute(SESSION_OF, (digest(token),)).fetchone()
    assert row is not None
    revoked_at, last_activity_at, reason = row
    assert reason == "material_privilege_reduction"
    assert revoked_at == last_activity_at


def test_the_revocation_time_migration_changes_only_the_trigger_function_and_is_forward_only(
    revocation_database: RevocationDatabase,
) -> None:
    """The trigger function keeps its attributes (not a definer, search path `pg_catalog`,
    volatile, returns trigger), no application role may execute it, and it holds the new
    revocation time; the migration follows `20270126_183` and refuses a downgrade."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with psycopg.connect(revocation_database.owner_url) as connection:
        facts = connection.execute(FUNCTION_FACTS).fetchone()
        assert facts is not None
        _, definer, settings, _, volatility, returns, _ = facts
        assert (definer, settings, volatility, returns) == (
            False,
            ["search_path=pg_catalog"],
            "v",
            "trigger",
        )
        for role in ("prm_runtime", "prm_financial"):
            allowed = connection.execute(
                "SELECT pg_catalog.has_function_privilege(%s, "
                "'app.protect_browser_session_lifecycle()', 'EXECUTE')",
                (role,),
            ).fetchone()
            assert allowed == (False,), role
        source = connection.execute(
            "SELECT prosrc FROM pg_catalog.pg_proc "
            "WHERE oid = 'app.protect_browser_session_lifecycle()'::regprocedure"
        ).fetchone()
    assert source is not None
    assert "GREATEST(operation_time, OLD.last_activity_at)" in source[0]
