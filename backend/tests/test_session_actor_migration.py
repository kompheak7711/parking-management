"""Login sub-slice L3a-2: the signed-in actor of a request, read from its session cookie.

DL-057, API-008, API-097, SEC-002, SEC-016, SEC-017, DB-AUTH-004, DB-AUTH-007. One throwaway
database at head with the default bundles seeded; the Staff account is made by the Owner through
the administration flow, signs in through `PostgresAuthenticationFlow` and is resolved by
`PostgresSessionActorResolver` as the runtime role.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request

from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from property_rental.access_control import STAFF_DEFAULT_BUNDLE_CAPABILITIES
from property_rental.app import create_app
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.identity import ObjectScope
from property_rental.session_actor import PostgresSessionActorResolver
from property_rental.settings import Settings
from test_access_admin_flow_migration import allow_admin_actions, context
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

PASSWORD = "correct horse battery staple"
ADD_OLD_SESSION = """
    INSERT INTO app.browser_sessions (
        session_id, actor_id, token_verifier, verifier_algorithm, created_at, last_activity_at,
        idle_expires_at, absolute_expires_at, creation_provenance
    )
    SELECT %s, %s, %s, 'sha256', moment.created, moment.created,
           LEAST(moment.created + interval '30 minutes', moment.created + interval '24 hours'),
           moment.created + interval '24 hours', 'login-slice-l3a-2-test'
    FROM (SELECT statement_timestamp() - %s::interval AS created) AS moment
"""
LAST_ACTIVITY = "SELECT last_activity_at FROM app.browser_sessions WHERE token_verifier = %s"


@dataclass(frozen=True)
class ActorDatabase:
    owner_url: str
    runtime_url: str
    property_id: str
    owner: uuid.UUID
    manager: uuid.UUID


@pytest.fixture(scope="module")
def actor_database(migrated_database_url: str) -> Iterator[ActorDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_session_actor") as temporary:
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
        yield ActorDatabase(temporary, runtime_url, str(property_id), owner, manager)


def signed_in_staff(database: ActorDatabase, username: str) -> tuple[uuid.UUID, str]:
    """A Staff account made by the Owner (with the default Staff bundle), signed in."""
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


def request_with(cookie: str | None) -> Request:
    headers = [] if cookie is None else [(b"cookie", cookie.encode("latin-1"))]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def session_cookie(token: str) -> str:
    return f"__Host-prm_session={token}"


def last_activity(database: ActorDatabase, token: str) -> Any:
    with psycopg.connect(database.owner_url) as connection:
        row = connection.execute(
            LAST_ACTIVITY, (hashlib.sha256(token.encode("utf-8")).digest(),)
        ).fetchone()
    assert row is not None
    return row[0]


def test_the_resolver_gives_the_session_account_its_bundle_grants_and_records_activity(
    actor_database: ActorDatabase,
) -> None:
    """A signed-in Staff account resolves to exactly the capabilities of the default Staff bundle
    for the Property, with the `actor` scope of itself on `identity.read_self`; each resolved
    request records the activity by the database clock; through `create_app`, `/identity/me`
    answers the actor with the cookie and 401 without it."""
    staff, token = signed_in_staff(actor_database, "l3a-2.staff")
    resolver = PostgresSessionActorResolver(actor_database.runtime_url)
    before = last_activity(actor_database, token)
    actor = resolver(request_with(session_cookie(token)))
    assert actor is not None and actor.actor_id == str(staff)
    assert {grant.capability for grant in actor.capability_grants} == (
        STAFF_DEFAULT_BUNDLE_CAPABILITIES
    )
    for grant in actor.capability_grants:
        assert grant.property_ids == frozenset({actor_database.property_id})
        own = {ObjectScope("actor", str(staff))}
        expected_scopes = own if grant.capability == "identity.read_self" else set()
        assert grant.object_scopes == expected_scopes, grant.capability
    assert last_activity(actor_database, token) > before

    app = create_app(Settings(database_url=SecretStr(actor_database.runtime_url)))
    with TestClient(app, base_url="https://testserver") as client:
        me = client.get(
            "/api/v1/identity/me",
            headers={"Cookie": session_cookie(token), "X-Request-ID": "l3a-2-me"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["data"]["actor_id"] == str(staff)
        anonymous = client.get("/api/v1/identity/me", headers={"X-Request-ID": "l3a-2-none"})
        assert anonymous.status_code == 401
        # Review round 1: after sign-out the same cookie answers 401.
        PostgresAuthenticationFlow(actor_database.runtime_url).logout(
            session_token=token, request_id="l3a-2-out"
        )
        after = client.get(
            "/api/v1/identity/me",
            headers={"Cookie": session_cookie(token), "X-Request-ID": "l3a-2-after"},
        )
        assert after.status_code == 401


def test_a_bundle_given_or_removed_counts_at_the_next_request(
    actor_database: ActorDatabase,
) -> None:
    """SEC-017: the grants are read fresh on every request, so a bundle the Owner assigns counts
    at the next request without a new sign-in, and removing it ends the account's sessions
    (the L2a removal revokes them), so the next request has no actor."""
    staff, token = signed_in_staff(actor_database, "l3a-2.extra")
    resolver = PostgresSessionActorResolver(actor_database.runtime_url)
    actor = resolver(request_with(session_cookie(token)))
    assert actor is not None
    assert "audit.view" not in {grant.capability for grant in actor.capability_grants}

    admin = PostgresAccessAdministrationFlow(actor_database.runtime_url)
    extra = admin.create_role_bundle(
        property_id=actor_database.property_id,
        name=f"Audit desk {uuid.uuid4().hex[:8]}",
        capability_ids=("audit.view",),
        audit_context=context(actor_database.owner),
    )
    admin.assign_role_bundle(
        user_id=staff,
        role_bundle_id=extra.role_bundle_id,
        property_id=actor_database.property_id,
        audit_context=context(actor_database.owner),
    )
    actor = resolver(request_with(session_cookie(token)))
    assert actor is not None
    assert "audit.view" in {grant.capability for grant in actor.capability_grants}

    admin.remove_role_assignment(
        user_id=staff,
        role_bundle_id=extra.role_bundle_id,
        property_id=actor_database.property_id,
        reason="cover week ended",
        audit_context=context(actor_database.owner),
    )
    assert resolver(request_with(session_cookie(token))) is None


def test_no_actor_without_a_live_session_of_an_active_account_that_needs_no_mfa(
    actor_database: ActorDatabase,
) -> None:
    """No cookie, a token that is unknown or too long, a signed-out session, a session idle for
    31 minutes, the session of an account disabled after sign-in and a session of a Manager
    (MFA policy `required`, written as the table owner) all give no actor, and the last three
    get no activity."""
    resolver = PostgresSessionActorResolver(actor_database.runtime_url)
    assert resolver(request_with(None)) is None
    for token in (secrets.token_urlsafe(32), "x" * 129):
        assert resolver(request_with(session_cookie(token))) is None

    _, signed_out = signed_in_staff(actor_database, "l3a-2.out")
    PostgresAuthenticationFlow(actor_database.runtime_url).logout(
        session_token=signed_out, request_id="l3a-2"
    )
    assert resolver(request_with(session_cookie(signed_out))) is None

    disabled, disabled_token = signed_in_staff(actor_database, "l3a-2.disabled")
    idle_staff, _ = signed_in_staff(actor_database, "l3a-2.idle")
    idle_token, manager_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with psycopg.connect(actor_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state = 'disabled' WHERE actor_id = %s",
            (disabled,),
        )
        for actor_id, token, age in (
            (idle_staff, idle_token, "31 minutes"),
            (actor_database.manager, manager_token, "1 minute"),
        ):
            connection.execute(
                ADD_OLD_SESSION,
                (uuid.uuid4(), actor_id, hashlib.sha256(token.encode("utf-8")).digest(), age),
            )
        connection.commit()
    for token in (disabled_token, idle_token, manager_token):
        before = last_activity(actor_database, token)
        assert resolver(request_with(session_cookie(token))) is None
        # Review round 2: a session the resolver refuses gets no activity.
        assert last_activity(actor_database, token) == before
