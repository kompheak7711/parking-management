"""The signed-in actor of a request, read from its session cookie (login sub-slice L3a-2, DL-081).

`PostgresSessionActorResolver` replaces `deny_unauthenticated_actor` when a database is set. On
every request it records the session's activity and reads the account's grants fresh from the
database, so a removed capability, bundle or account stops working at the next request (SEC-017).
A request without a live session gets no actor (401); a database error answers 503.
"""

from typing import Final, cast
from uuid import UUID

import psycopg
from fastapi import Request
from psycopg import IsolationLevel

from property_rental.access_admin_api import ACCESS_ADMIN_CAPABILITY
from property_rental.access_admin_flow import (
    PostgresAccessAdministrationScopeReader,
    with_administration_scopes,
)
from property_rental.access_control import (
    CapabilityCatalogMismatch,
    GrantConnection,
    PostgresCapabilityGrantReader,
)
from property_rental.api import IDENTITY_READ_SELF_CAPABILITY
from property_rental.auth_api import (
    SESSION_COOKIE_NAME,
    AuthenticationRejected,
    AuthenticationUnavailable,
)
from property_rental.auth_flow import (
    CONNECT_TIMEOUT_SECONDS,
    LIVE_SESSION,
    SESSION_MFA_SATISFIED,
    STATEMENT_TIMEOUT_OPTION,
    session_token_digest,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope

# The session's activity (DB-AUTH-004): the trigger sets the new idle expiry, never past the
# absolute one. The guard on `last_activity_at` skips the write when a parallel request already
# recorded a later activity, so the trigger never sees time going back; a session of an account
# that may not be resolved (disabled, unclassified, needing MFA without an MFA proof) gets no
# activity (review round 1; login sub-slice L3c-2a).
RECORD_ACTIVITY: Final = f"""
    UPDATE app.browser_sessions AS browser
    SET last_activity_at = statement_timestamp()
    WHERE browser.token_verifier = %s
      AND browser.revoked_at IS NULL
      AND browser.last_activity_at < statement_timestamp()
      AND statement_timestamp() < browser.idle_expires_at
      AND statement_timestamp() < browser.absolute_expires_at
      AND EXISTS (
          SELECT 1
          FROM app.user_accounts AS account
          JOIN app.user_account_classes AS classification
            ON classification.actor_id = account.actor_id
          WHERE account.actor_id = browser.actor_id
            AND account.lifecycle_state = 'active'
            AND {SESSION_MFA_SATISFIED}
      )
"""


def with_own_actor_scope(
    grants: frozenset[CapabilityGrant], actor_id: str
) -> frozenset[CapabilityGrant]:
    """Give `identity.read_self` the `actor` object scope of the actor itself only."""
    scope = ObjectScope(object_type="actor", object_id=actor_id)
    return frozenset(
        CapabilityGrant(
            capability=grant.capability,
            property_ids=grant.property_ids,
            object_scopes=grant.object_scopes | {scope},
        )
        if grant.capability == IDENTITY_READ_SELF_CAPABILITY
        else grant
        for grant in grants
    )


class PostgresSessionActorResolver:
    """`ActorResolver` from the `__Host-prm_session` cookie; building it opens no connection."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._scopes = PostgresAccessAdministrationScopeReader(database_url)

    def __call__(self, request: Request) -> AuthenticatedActor | None:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            return None
        try:
            digest = session_token_digest(session_token)
        except AuthenticationRejected:
            return None
        try:
            with psycopg.connect(
                self._database_url,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                options=STATEMENT_TIMEOUT_OPTION,
            ) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.execute(RECORD_ACTIVITY, (digest,))
                # Read after the activity write, in the same transaction, so a session revoked
                # or expired meanwhile gives no actor.
                row = connection.execute(LIVE_SESSION, (digest,)).fetchone()
                if row is None:
                    return None
                actor_id = str(row[1])
                grants = PostgresCapabilityGrantReader(
                    cast(GrantConnection, connection)
                ).grants_for(UUID(actor_id))
        except (psycopg.Error, CapabilityCatalogMismatch) as exc:
            raise AuthenticationUnavailable from exc
        if any(grant.capability == ACCESS_ADMIN_CAPABILITY for grant in grants):
            grants = with_administration_scopes(grants, self._scopes.object_scopes(UUID(actor_id)))
        return AuthenticatedActor(
            actor_id=actor_id, capability_grants=with_own_actor_scope(grants, actor_id)
        )
