"""Login sub-slice L3a-2 unit tests: the actor scope of `identity.read_self` and fail closed when
the database cannot be reached (DL-081, API-008, SEC-002)."""

from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from starlette.requests import Request

from property_rental.access_control import (
    CapabilityCatalogMismatch,
    PostgresCapabilityGrantReader,
)
from property_rental.auth_api import AuthenticationUnavailable
from property_rental.identity import CapabilityGrant, ObjectScope
from property_rental.session_actor import PostgresSessionActorResolver, with_own_actor_scope


def request_with(cookie: str | None) -> Request:
    headers = [] if cookie is None else [(b"cookie", cookie.encode("latin-1"))]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_only_identity_read_self_gets_the_actor_scope_of_the_actor_itself() -> None:
    grants = frozenset(
        {
            CapabilityGrant("identity.read_self", frozenset({"p"})),
            CapabilityGrant("customers.read", frozenset({"p"})),
        }
    )
    scoped = {grant.capability: grant for grant in with_own_actor_scope(grants, "actor-1")}
    own = frozenset({ObjectScope("actor", "actor-1")})
    assert scoped["identity.read_self"].object_scopes == own
    assert scoped["identity.read_self"].property_ids == frozenset({"p"})
    assert scoped["customers.read"].object_scopes == frozenset()


def test_the_resolver_fails_closed_and_needs_no_database_without_a_cookie() -> None:
    """No cookie, or a token over 128 characters, gives no actor without a database; a session
    cookie with a database that cannot be reached answers unavailable (503), never an actor."""
    resolver = PostgresSessionActorResolver("postgresql://prm@127.0.0.1:1/unused")
    assert resolver(request_with(None)) is None
    assert resolver(request_with("__Host-prm_session=" + "x" * 129)) is None
    with pytest.raises(AuthenticationUnavailable):
        resolver(request_with("__Host-prm_session=" + "t" * 43))


class _Result:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    """A stand-in for the resolver's connection: the activity write, then the live session."""

    def __init__(self, actor_id: UUID) -> None:
        self.isolation_level: object = None
        self._rows: list[tuple[object, ...] | None] = [None, (uuid4(), str(actor_id))]

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> _Result:
        return _Result(self._rows.pop(0))


class _Scopes:
    def __init__(self) -> None:
        self.asked: list[UUID] = []

    def object_scopes(self, actor_id: UUID) -> frozenset[ObjectScope]:
        self.asked.append(actor_id)
        return frozenset({ObjectScope("user_account", "account-1")})


def test_the_owner_gets_its_administration_scopes_on_identity_manage_access_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1: no Owner session can be resolved before login sub-slice L3c (the Owner
    needs MFA), so the Owner branch is checked with stand-ins: `identity.manage_access` gets the
    Owner's administration scopes, `identity.read_self` the actor's own scope, and no other grant
    gets a scope."""
    owner = uuid4()
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Connection(owner))

    def grants(self: Any, actor_id: UUID) -> frozenset[CapabilityGrant]:
        assert actor_id == owner
        return frozenset(
            {
                CapabilityGrant("identity.manage_access", frozenset({"p"})),
                CapabilityGrant("identity.read_self", frozenset({"p"})),
                CapabilityGrant("settings.manage", frozenset({"p"})),
            }
        )

    monkeypatch.setattr(PostgresCapabilityGrantReader, "grants_for", grants)
    resolver = PostgresSessionActorResolver("postgresql://unused.invalid/unused")
    scopes = _Scopes()
    monkeypatch.setattr(resolver, "_scopes", scopes)
    actor = resolver(request_with("__Host-prm_session=" + "t" * 43))
    assert actor is not None and actor.actor_id == str(owner)
    by_name = {grant.capability: grant for grant in actor.capability_grants}
    assert by_name["identity.manage_access"].object_scopes == frozenset(
        {ObjectScope("user_account", "account-1")}
    )
    assert by_name["identity.read_self"].object_scopes == frozenset(
        {ObjectScope("actor", str(owner))}
    )
    assert by_name["settings.manage"].object_scopes == frozenset()
    assert scopes.asked == [owner]


def test_a_capability_the_catalog_does_not_know_answers_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1: a grant the application catalog refuses gives no actor with partial
    grants; the request answers unavailable (503)."""
    actor_id = uuid4()
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Connection(actor_id))

    def mismatch(self: Any, actor_id: UUID) -> frozenset[CapabilityGrant]:
        raise CapabilityCatalogMismatch

    monkeypatch.setattr(PostgresCapabilityGrantReader, "grants_for", mismatch)
    resolver = PostgresSessionActorResolver("postgresql://unused.invalid/unused")
    with pytest.raises(AuthenticationUnavailable):
        resolver(request_with("__Host-prm_session=" + "t" * 43))
