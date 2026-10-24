"""PostgreSQL account and role bundle administration flow (login slice sub-slice L2b-2).

API-079, API-080, DL-081, SEC-014, SEC-021, SEC-075, DB-AUTH-010: every change goes through the
audited, Owner-only `app.admin_*` definer functions, one READ COMMITTED transaction per call. Each
change reads its result back and checks it in the same transaction, before the commit. Database
errors become stable codes with fixed plain messages; database text is never passed on.
"""

import json
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Final, Literal, TypeVar, cast
from uuid import UUID, uuid5

import psycopg
from psycopg import IsolationLevel

from property_rental.access_admin_api import (
    ACCESS_ADMIN_CAPABILITY,
    ROLE_BUNDLE_OBJECT_TYPE,
    USER_ACCOUNT_OBJECT_TYPE,
    AccessAdministrationNotFound,
    AccessAdministrationRejected,
    AccessAdministrationUnavailable,
    AccountClass,
    AdministrationAuditContext,
    AdministrativeRecoveryView,
    AuthorizationHistoryView,
    CapabilityView,
    CreatableAccountClass,
    OneTimePasswordView,
    RoleAssignmentView,
    RoleBundleView,
    UserAccountView,
)
from property_rental.auth_flow import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_SESSION_TOKEN_LENGTH,
    RECENT_SESSION_REAUTHENTICATION,
    STATEMENT_TIMEOUT_OPTION,
    session_token_digest,
)
from property_rental.identity import CapabilityGrant, ObjectScope
from property_rental.local_authentication import normalize_local_username
from property_rental.password_security import (
    PasswordCredentialMaterial,
    PasswordHashService,
    new_one_time_password,
)
from property_rental.visible_text import tidy_spaces, without_zero_width_spaces

# The request id pattern allows text that is not a UUID; such an id gets a stable UUID5 in this
# namespace as the audit correlation id.
CORRELATION_NAMESPACE: Final = UUID("6d3c1f0e-5b7a-4c2e-9f41-0a8e2b7d5c13")
ACCOUNTS: Final = (
    "SELECT actor_id::text, username, display_name, audit_name, lifecycle_state, "
    "mfa_policy_class, account_class, settings_access, version FROM app.admin_accounts(%s)"
)
BUNDLES: Final = (
    "SELECT role_bundle_id::text, property_id::text, name, version, capability_ids "
    "FROM app.admin_role_bundles(%s)"
)

# Login sub-slice L3d-2 (owner answer (a) to Q-2026-10-21-157): the actions that change who may
# do what need a reauthentication with the password and the sign-in code in the last 15
# minutes, checked on the database clock in the action's own transaction. Only the latest `totp`
# reauthentication of the request's own live session counts, found through the request's
# reauthentication cookie (L3d-1 review rounds 2 and 3), and only while its sign-in code is still
# the account's active one. The session is held `FOR SHARE` until the action commits, so a
# sign-out waits for it.
LOCK_TIMEOUT_OPTION: Final = "-c lock_timeout=3000"
RECENT_REAUTHENTICATION: Final = f"""{RECENT_SESSION_REAUTHENTICATION}    FOR SHARE OF browser
"""
# Login sub-slice L4 (owner answers (a) to Q-2026-10-21-153 and Q-2026-10-23-180,
# Q-2026-10-24-185): the Owner's reset, a new account's first password and a Staff account's MFA
# turned off each give a one-time password through `app.issue_one_time_password`, in the action's
# own transaction. A Staff account's MFA off takes the replacement locks before the account
# function (the same order as every replacement).
ISSUE_ONE_TIME_PASSWORD: Final = """
    SELECT issued_one_time_password_id, issued_expires_at, sign_in_code_reset,
           recovery_codes_ended, settings_access_ended, sessions_ended
    FROM app.issue_one_time_password(%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
"""
REPLACEMENT_LOCKS: Final = (
    "SELECT pg_advisory_xact_lock(hashtextextended('recovery-codes:' || %s::text, 0)), "
    "pg_advisory_xact_lock(hashtextextended('password-credential:' || %s::text, 0))"
)
MFA_POLICY_OF: Final = "SELECT mfa_policy_class FROM app.user_accounts WHERE actor_id = %s"
FIRST_PASSWORD_REASON: Final = "First password of a new account"
MFA_OFF_REASON: Final = "Sign-in code turned off"
REAUTHENTICATION_REQUIRED_MESSAGE: Final = (
    "Please enter your password and sign-in code again, then try again."
)


def _reauthentication_required() -> AccessAdministrationRejected:
    return AccessAdministrationRejected(
        403, "REAUTHENTICATION_REQUIRED", REAUTHENTICATION_REQUIRED_MESSAGE
    )


Row = tuple[object, ...]
Connection = psycopg.Connection[Row]
Result = TypeVar("Result")

# (status, code, plain message) for each known refusal, keyed by the database message or the
# constraint name. Anything not listed falls back to the generic answer of its SQLSTATE.
SIGN_IN_CODE_MESSAGE: Final = (
    "A Staff account gets Settings access only after it has set up its sign-in code."
)
KNOWN_REFUSALS: Final[dict[str, tuple[int, str, str]]] = {
    "user_accounts_normalized_username_key": (
        409,
        "USERNAME_TAKEN",
        "Another account already has this username.",
    ),
    "role_bundles_property_lower_name_key": (
        409,
        "ROLE_BUNDLE_NAME_TAKEN",
        "Another role bundle already has this name.",
    ),
    "a role bundle is already assigned to this account": (
        409,
        "ROLE_BUNDLE_ALREADY_ASSIGNED",
        "This account already has this role bundle.",
    ),
    "this account already has Settings access": (
        409,
        "SETTINGS_ACCESS_ALREADY_GIVEN",
        "This account already has Settings access.",
    ),
    "a Staff account gets Settings access only after it has set up its sign-in code": (
        409,
        "SIGN_IN_CODE_REQUIRED",
        SIGN_IN_CODE_MESSAGE,
    ),
    "this account has no Settings access": (
        409,
        "NO_SETTINGS_ACCESS",
        "This account has no Settings access.",
    ),
    "this account does not have that role bundle": (
        409,
        "ROLE_BUNDLE_NOT_ASSIGNED",
        "This account does not have this role bundle.",
    ),
    "a disabled account is not changed": (
        409,
        "ACCOUNT_DISABLED",
        "A disabled account cannot be changed.",
    ),
    "the Property has no default role bundles": (
        409,
        "PROPERTY_NOT_READY",
        "The Property is not ready for new accounts.",
    ),
    "the Property is not set up": (
        409,
        "PROPERTY_NOT_READY",
        "The Property is not set up.",
    ),
    "an account name is 1 to 128 visible characters with no space at either end": (
        422,
        "INVALID_NAME",
        "A name has 1 to 128 visible characters and no hidden characters.",
    ),
    "role_bundles_name_check": (
        422,
        "INVALID_NAME",
        "A name has 1 to 128 visible characters and no hidden characters.",
    ),
    "role_bundles_name_visible_check": (
        422,
        "INVALID_NAME",
        "A name has 1 to 128 visible characters and no hidden characters.",
    ),
    "only bundle capabilities can be in a role bundle": (
        422,
        "CAPABILITY_NOT_ASSIGNABLE",
        "This capability cannot be put in a role bundle.",
    ),
    "the Owner account is not changed by account administration": (
        422,
        "OWNER_ACCOUNT_NOT_CHANGED",
        "The Owner account is not changed here.",
    ),
    "an account without a class can only be disabled": (
        422,
        "ACCOUNT_WITHOUT_CLASS",
        "An account without a class can only be disabled.",
    ),
    "Settings access is given only to a Manager or Staff account": (
        422,
        "NOT_MANAGER_OR_STAFF",
        "Settings access is given only to an active Manager or Staff account.",
    ),
    "sessions are revoked here only for a Manager or Staff account": (
        422,
        "NOT_MANAGER_OR_STAFF",
        "This works only for a Manager or Staff account.",
    ),
    "a role bundle is assigned only to an active account with a class": (
        422,
        "NOT_MANAGER_OR_STAFF",
        "A role bundle is given only to an active account with a class.",
    ),
    "at least one account change is required": (
        422,
        "NO_CHANGE",
        "Nothing to change.",
    ),
    "at least one role bundle change is required": (
        422,
        "NO_CHANGE",
        "Nothing to change.",
    ),
    "an Owner or Manager account requires MFA": (
        422,
        "MANAGER_MFA_REQUIRED",
        "A Manager account always uses the sign-in code.",
    ),
    # Review round 1 (security): only the Owner check is a 403; any other 42501 (for example a
    # missing grant) is a misconfiguration and answers unavailable.
    "only the Owner administers accounts and role bundles": (
        403,
        "FORBIDDEN",
        "Access is not allowed.",
    ),
}
INVALID_NAME: Final = (
    422,
    "INVALID_NAME",
    "A name has 1 to 128 visible characters and no hidden characters.",
)
GENERIC_REFUSALS: Final[dict[str, tuple[int, str, str]]] = {
    "40001": (412, "STALE_VERSION", "The record changed since it was read. Reload it."),
    "23505": (409, "CONFLICT", "The request conflicts with the current state."),
    "22023": (422, "VALIDATION_ERROR", "The request is not valid."),
    "23514": (409, "TRY_AGAIN", "The change met another change. Try again."),
    "40P01": (409, "TRY_AGAIN", "The change met another change. Try again."),
    "55P03": (409, "TRY_AGAIN", "The change met another change. Try again."),
}


def correlation_id(request_id: str) -> UUID:
    """The request id as the audit correlation id."""
    try:
        return UUID(request_id)
    except ValueError:
        return uuid5(CORRELATION_NAMESPACE, request_id)


def normalized_name(value: str) -> str:
    """Without U+200B (Q-2026-10-22-169 (a)), NFC, with each run of space separators made one
    space and none at either end (Q-2026-10-22-170 (a)); control characters and line breaks are
    left for the database name check to refuse (review round 1)."""
    return tidy_spaces(unicodedata.normalize("NFC", without_zero_width_spaces(value)))


def normalized_username(value: str) -> str:
    """The sign-in lookup's DB-AUTH-001 normalization (U+200B removed, NFC, spaces tidied,
    lower case; Q-2026-10-22-170 (a)); any other white space, such as a tab or a line break, is
    refused (review round 1, security: two usernames must not look the same)."""
    username = normalize_local_username(value)
    if any(character.isspace() and character != " " for character in username):
        raise AccessAdministrationRejected(*INVALID_NAME)
    return username


def _owner(actor_id: str) -> UUID:
    try:
        return UUID(actor_id)
    except ValueError as exc:
        raise AccessAdministrationRejected(403, "FORBIDDEN", "Access is not allowed.") from exc


def _cursor_id(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        return str(UUID(cursor))
    except ValueError as exc:
        raise AccessAdministrationRejected(
            422, "VALIDATION_ERROR", "The page cursor is not valid."
        ) from exc


def _refusal(exc: psycopg.Error) -> Exception:
    """A database error as a stable refusal; database text is never passed on."""
    state = exc.sqlstate
    if state == "P0002":
        return AccessAdministrationNotFound()
    for key in (exc.diag.message_primary, exc.diag.constraint_name):
        if key is not None and key in KNOWN_REFUSALS:
            return AccessAdministrationRejected(*KNOWN_REFUSALS[key])
    if state is not None and state in GENERIC_REFUSALS:
        return AccessAdministrationRejected(*GENERIC_REFUSALS[state])
    # psycopg raises every SQLSTATE class 22 error as a `DataError`, so it is checked only after
    # the known messages; a NUL character in a text value is one of them (no SQLSTATE).
    if isinstance(exc, psycopg.DataError):
        return AccessAdministrationRejected(422, "VALIDATION_ERROR", "The request is not valid.")
    # Isolation-level refusals (55000) and anything unknown: fail closed as unavailable.
    return AccessAdministrationUnavailable()


def _page(
    items: list[Result],
    key: Callable[[Result], str],
    cursor: str | None,
    limit: int,
) -> tuple[tuple[Result, ...], str | None]:
    ordered = sorted(items, key=key)
    if cursor is not None:
        ordered = [item for item in ordered if key(item) > cursor]
    page = ordered[:limit]
    next_cursor = key(page[-1]) if len(ordered) > limit else None
    return tuple(page), next_cursor


def _lifecycle(value: object) -> Literal["active", "disabled"]:
    if value not in ("active", "disabled"):
        raise AccessAdministrationUnavailable
    return value


def _mfa(value: object) -> Literal["required", "optional"]:
    if value not in ("required", "optional"):
        raise AccessAdministrationUnavailable
    return value


def _outcome(value: object) -> Literal["completed", "rejected"]:
    # Administration events are written only when they succeed; anything else fails closed.
    if value != "SUCCEEDED":
        raise AccessAdministrationUnavailable
    return "completed"


def _account_class(value: object) -> AccountClass | None:
    if value is not None and value not in ("owner", "manager", "staff"):
        raise AccessAdministrationUnavailable
    return value


class PostgresAccessAdministrationFlow:
    """`AccessAdministrationFlow` on PostgreSQL through the audited `app.admin_*` functions."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._password_service = PasswordHashService()

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        """One action's connection, with the time limits of the sign-in flow and a lock wait
        limit (login sub-slice L3d-2 review round 1, security): the check holds the Owner's
        session `FOR SHARE` for the whole action, so a stuck action must not hold it long."""
        try:
            with psycopg.connect(
                self._database_url,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                options=f"{STATEMENT_TIMEOUT_OPTION} {LOCK_TIMEOUT_OPTION}",
            ) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                yield connection
        except psycopg.Error as exc:
            raise _refusal(exc) from exc

    @staticmethod
    def _property_id(connection: Connection) -> str:
        row = connection.execute("SELECT id::text FROM app.properties").fetchone()
        if row is None:
            raise AccessAdministrationNotFound
        return str(row[0])

    @staticmethod
    def _accounts(connection: Connection, owner: UUID, property_id: str) -> list[UserAccountView]:
        return [
            UserAccountView(
                user_id=UUID(str(row[0])),
                property_id=property_id,
                username=str(row[1]),
                display_name=str(row[2]),
                audit_name=str(row[3]),
                lifecycle_state=_lifecycle(row[4]),
                mfa_policy_class=_mfa(row[5]),
                version=int(str(row[8])),
                account_class=_account_class(row[6]),
                settings_access=bool(row[7]),
            )
            for row in connection.execute(ACCOUNTS, (owner,)).fetchall()
        ]

    def _account(self, connection: Connection, owner: UUID, user_id: UUID) -> UserAccountView:
        property_id = self._property_id(connection)
        for account in self._accounts(connection, owner, property_id):
            if account.user_id == user_id:
                return account
        raise AccessAdministrationUnavailable

    @staticmethod
    def _bundles(connection: Connection, owner: UUID) -> list[RoleBundleView]:
        return [
            RoleBundleView(
                role_bundle_id=UUID(str(row[0])),
                property_id=str(row[1]),
                name=str(row[2]),
                capability_ids=tuple(str(item) for item in cast(list[object], row[4])),
                version=int(str(row[3])),
            )
            for row in connection.execute(BUNDLES, (owner,)).fetchall()
        ]

    def _bundle(self, connection: Connection, owner: UUID, role_bundle_id: UUID) -> RoleBundleView:
        for bundle in self._bundles(connection, owner):
            if bundle.role_bundle_id == role_bundle_id:
                return bundle
        raise AccessAdministrationUnavailable

    @staticmethod
    def _require_owner(connection: Connection, owner: UUID) -> None:
        """The database's Owner check for a read the runtime role could do alone (review
        round 1, security): any other actor gets 42501, a 403."""
        connection.execute("SELECT 1 FROM app.admin_role_bundles(%s) LIMIT 1", (owner,))

    @staticmethod
    def _require_recent_reauthentication(
        connection: Connection, audit_context: AdministrationAuditContext
    ) -> None:
        """A recent reauthentication of the request's own session (login sub-slice L3d-2): the
        first statement of the action's transaction; without one, 403 `REAUTHENTICATION_REQUIRED`
        and nothing is written. It never replaces the capability check (SEC-018)."""
        tokens = (audit_context.session_token, audit_context.reauthentication_token)
        if any(not token or len(token) > MAX_SESSION_TOKEN_LENGTH for token in tokens):
            raise _reauthentication_required()
        session_token, reauthentication_token = cast(tuple[str, str], tokens)
        found = connection.execute(
            RECENT_REAUTHENTICATION,
            (
                session_token_digest(session_token),
                _owner(audit_context.actor_id),
                session_token_digest(reauthentication_token),
            ),
        ).fetchone()
        if found is None:
            raise _reauthentication_required()

    @staticmethod
    def _call(connection: Connection, query: str, parameters: tuple[object, ...]) -> object:
        row = connection.execute(query, parameters).fetchone()
        if row is None or row[0] is None:
            raise AccessAdministrationUnavailable
        return row[0]

    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        del request_id
        owner, after = _owner(actor_id), _cursor_id(cursor)
        with self._transaction() as connection:
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            accounts = self._accounts(connection, owner, property_id)
        return _page(accounts, lambda account: str(account.user_id), after, limit)

    def create_user(
        self,
        *,
        property_id: str,
        username: str,
        display_name: str,
        audit_name: str,
        account_class: CreatableAccountClass,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        owner = _owner(audit_context.actor_id)
        one_time_password, credential = self._new_one_time_password()
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            created = self._call(
                connection,
                "SELECT app.admin_create_account(%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    normalized_username(username),
                    normalized_name(display_name),
                    normalized_name(audit_name),
                    account_class,
                    correlation_id(audit_context.request_id),
                ),
            )
            account = self._account(connection, owner, UUID(str(created)))
            expected_mfa = "required" if account_class == "manager" else "optional"
            if (
                account.account_class != account_class
                or account.mfa_policy_class != expected_mfa
                or account.version != 1
                or account.username != normalized_username(username)
                or account.display_name != normalized_name(display_name)
                or account.audit_name != normalized_name(audit_name)
            ):
                raise AccessAdministrationUnavailable
            # Q-2026-10-21-153 (a): the first password is a one-time password, in the same step.
            issued = self._issue_one_time_password(
                connection,
                owner=owner,
                user_id=account.user_id,
                reason=FIRST_PASSWORD_REASON,
                reset_mfa=False,
                credential=credential,
                request_id=audit_context.request_id,
            )
        return replace(
            account,
            one_time_password=OneTimePasswordView(
                value=one_time_password, expires_at=cast(datetime, issued[1])
            ),
        )

    def user_property_id(self, *, user_id: UUID) -> str | None:
        with self._transaction() as connection:
            found = connection.execute(
                "SELECT 1 FROM app.user_accounts WHERE actor_id = %s", (user_id,)
            ).fetchone()
            return None if found is None else self._property_id(connection)

    def update_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        expected_version: int,
        display_name: str | None,
        audit_name: str | None,
        lifecycle_state: Literal["disabled"] | None,
        mfa_policy_class: Literal["required", "optional"] | None,
        revoke_applicable_sessions_if_disabled: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        # The database function revokes the sessions of a disabled account in the same step.
        del revoke_applicable_sessions_if_disabled
        owner = _owner(audit_context.actor_id)
        # The slow hashing comes before the locks (review round 1); unused unless MFA was required.
        prepared = self._new_one_time_password() if mfa_policy_class == "optional" else None
        with self._transaction() as connection:
            if lifecycle_state is not None or mfa_policy_class is not None:
                # Disabling an account or turning its MFA on or off (Q-2026-10-21-157
                # (a)); a change of the names alone is not on the list.
                self._require_recent_reauthentication(connection, audit_context)
            mfa_turned_off = False
            if mfa_policy_class == "optional":
                # Q-2026-10-23-180 (a): a Staff account's MFA turned off also replaces the
                # password with a one-time password and ends the recovery codes, in this step;
                # the replacement locks first (Q-2026-10-24-185 point 5).
                connection.execute(REPLACEMENT_LOCKS, (user_id, user_id))
                before = connection.execute(MFA_POLICY_OF, (user_id,)).fetchone()
                mfa_turned_off = before is not None and before[0] == "required"
            version = self._call(
                connection,
                "SELECT app.admin_update_account(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    user_id,
                    expected_version,
                    None if display_name is None else normalized_name(display_name),
                    None if audit_name is None else normalized_name(audit_name),
                    lifecycle_state == "disabled",
                    mfa_policy_class,
                    correlation_id(audit_context.request_id),
                ),
            )
            account = self._account(connection, owner, user_id)
            if (
                account.property_id != property_id
                or version != expected_version + 1
                or account.version != expected_version + 1
                or (
                    display_name is not None
                    and account.display_name != normalized_name(display_name)
                )
                or (audit_name is not None and account.audit_name != normalized_name(audit_name))
                or (lifecycle_state is not None and account.lifecycle_state != lifecycle_state)
                or (mfa_policy_class is not None and account.mfa_policy_class != mfa_policy_class)
            ):
                raise AccessAdministrationUnavailable
            # A request that also disables the account gives no one-time password: a disabled
            # account cannot sign in, and no path makes it active again.
            if mfa_turned_off and account.lifecycle_state == "active" and prepared is not None:
                one_time_password, credential = prepared
                issued = self._issue_one_time_password(
                    connection,
                    owner=owner,
                    user_id=user_id,
                    reason=MFA_OFF_REASON,
                    reset_mfa=True,
                    credential=credential,
                    request_id=audit_context.request_id,
                )
                return replace(
                    account,
                    one_time_password=OneTimePasswordView(
                        value=one_time_password, expires_at=cast(datetime, issued[1])
                    ),
                )
        return account

    def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        audit_context: AdministrationAuditContext,
    ) -> int:
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            revoked = self._call(
                connection,
                "SELECT app.admin_revoke_account_sessions(%s,%s,%s)",
                (owner, user_id, correlation_id(audit_context.request_id)),
            )
            count = int(str(revoked))
        return count

    def list_capabilities(
        self,
        *,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[CapabilityView, ...], str | None]:
        del request_id
        owner = _owner(actor_id)
        with self._transaction() as connection:
            self._require_owner(connection, owner)
            rows = connection.execute(
                "SELECT capability_id, description FROM app.capabilities "
                "WHERE grant_path = 'bundle'"
            ).fetchall()
        capabilities = [
            CapabilityView(capability_id=str(row[0]), name=str(row[0]), description=str(row[1]))
            for row in rows
        ]
        return _page(capabilities, lambda capability: capability.capability_id, cursor, limit)

    def list_role_bundles(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[RoleBundleView, ...], str | None]:
        del request_id
        owner, after = _owner(actor_id), _cursor_id(cursor)
        with self._transaction() as connection:
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            bundles = [
                bundle
                for bundle in self._bundles(connection, owner)
                if bundle.property_id == property_id
            ]
        return _page(bundles, lambda bundle: str(bundle.role_bundle_id), after, limit)

    def create_role_bundle(
        self,
        *,
        property_id: str,
        name: str,
        capability_ids: tuple[str, ...],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            created = self._call(
                connection,
                "SELECT app.admin_create_role_bundle(%s,%s,%s,%s,%s)",
                (
                    owner,
                    UUID(property_id),
                    normalized_name(name),
                    list(capability_ids),
                    correlation_id(audit_context.request_id),
                ),
            )
            bundle = self._bundle(connection, owner, UUID(str(created)))
            if (
                bundle.version != 1
                or bundle.property_id != property_id
                or bundle.name != normalized_name(name)
                or set(bundle.capability_ids) != set(capability_ids)
            ):
                raise AccessAdministrationUnavailable
        return bundle

    def role_bundle_property_id(self, *, role_bundle_id: UUID) -> str | None:
        # The runtime role cannot read the bundle relations. The deployment has one Property and
        # every bundle belongs to it; an unknown bundle is refused by the object scope check or,
        # as not found, by the database function.
        del role_bundle_id
        with self._transaction() as connection:
            return self._property_id(connection)

    def update_role_bundle(
        self,
        *,
        role_bundle_id: UUID,
        property_id: str,
        expected_version: int,
        name: str | None,
        capability_ids: tuple[str, ...] | None,
        revoke_affected_sessions_on_capability_reduction: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        # The database function revokes the sessions of a smaller bundle's holders in the same step.
        del revoke_affected_sessions_on_capability_reduction
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            version = self._call(
                connection,
                "SELECT app.admin_update_role_bundle(%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    role_bundle_id,
                    expected_version,
                    None if name is None else normalized_name(name),
                    None if capability_ids is None else list(capability_ids),
                    correlation_id(audit_context.request_id),
                ),
            )
            bundle = self._bundle(connection, owner, role_bundle_id)
            if (
                bundle.property_id != property_id
                or version != expected_version + 1
                or bundle.version != expected_version + 1
                or (
                    capability_ids is not None and set(bundle.capability_ids) != set(capability_ids)
                )
                or (name is not None and bundle.name != normalized_name(name))
            ):
                raise AccessAdministrationUnavailable
        return bundle

    def assign_role_bundle(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            self._call(
                connection,
                "SELECT app.admin_assign_role_bundle(%s,%s,%s,%s)",
                (owner, user_id, role_bundle_id, correlation_id(audit_context.request_id)),
            )
        return RoleAssignmentView(
            user_id=user_id, role_bundle_id=role_bundle_id, property_id=property_id
        )

    def remove_role_assignment(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            self._call(
                connection,
                "SELECT app.admin_remove_role_assignment(%s,%s,%s,%s,%s)",
                (owner, user_id, role_bundle_id, reason, correlation_id(audit_context.request_id)),
            )
        return RoleAssignmentView(
            user_id=user_id, role_bundle_id=role_bundle_id, property_id=property_id
        )

    def _change_settings_access(
        self,
        query: str,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
        expected: bool,
    ) -> UserAccountView:
        owner = _owner(audit_context.actor_id)
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            self._call(
                connection,
                query,
                (owner, user_id, reason, correlation_id(audit_context.request_id)),
            )
            account = self._account(connection, owner, user_id)
            if account.property_id != property_id or account.settings_access is not expected:
                raise AccessAdministrationUnavailable
        return account

    def give_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        return self._change_settings_access(
            "SELECT app.admin_give_settings_access(%s,%s,%s,%s)",
            user_id=user_id,
            property_id=property_id,
            reason=reason,
            audit_context=audit_context,
            expected=True,
        )

    def remove_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        return self._change_settings_access(
            "SELECT app.admin_remove_settings_access(%s,%s,%s,%s)",
            user_id=user_id,
            property_id=property_id,
            reason=reason,
            audit_context=audit_context,
            expected=False,
        )

    def list_authorization_history(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[AuthorizationHistoryView, ...], str | None]:
        del request_id
        owner = _owner(actor_id)
        after: tuple[datetime, UUID] | None = None
        if cursor is not None:
            moment, _, event = cursor.partition("|")
            try:
                after = (datetime.fromisoformat(moment), UUID(event))
            except ValueError as exc:
                raise AccessAdministrationRejected(
                    422, "VALIDATION_ERROR", "The page cursor is not valid."
                ) from exc
        with self._transaction() as connection:
            self._require_owner(connection, owner)
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            rows = connection.execute(
                "SELECT id, occurred_at, action, actor_id::text, entity_id::text, outcome "
                "FROM app.audit_events "
                "WHERE authorization_reference = 'identity.manage_access' "
                "AND action LIKE 'identity.%%' AND property_id::text = %s "
                "AND (%s::timestamptz IS NULL OR (occurred_at, id) > (%s::timestamptz, %s::uuid)) "
                "ORDER BY occurred_at, id LIMIT %s",
                (
                    property_id,
                    None if after is None else after[0],
                    None if after is None else after[0],
                    None if after is None else after[1],
                    limit + 1,
                ),
            ).fetchall()
        events = tuple(
            AuthorizationHistoryView(
                event_id=UUID(str(row[0])),
                property_id=property_id,
                occurred_at=cast(datetime, row[1]),
                action=str(row[2]),
                actor_id=str(row[3]),
                target_id=str(row[4]),
                outcome=_outcome(row[5]),
            )
            for row in rows[:limit]
        )
        next_cursor = (
            f"{events[-1].occurred_at.isoformat()}|{events[-1].event_id}"
            if len(rows) > limit
            else None
        )
        return events, next_cursor

    def administratively_recover_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reset_mfa: bool,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> AdministrativeRecoveryView:
        """The Owner's reset with a one-time password (login sub-slice L4, owner answer (a) to
        Q-2026-10-21-153): the recent reauthentication first (L3d-2 binding), then
        `app.issue_one_time_password` (only a Manager or Staff account; "also reset MFA" also
        ends the recovery codes and the Settings access); every session of the account ends.
        The one-time password is answered once and never kept."""
        owner = _owner(audit_context.actor_id)
        one_time_password, credential = self._new_one_time_password()
        with self._transaction() as connection:
            self._require_recent_reauthentication(connection, audit_context)
            if self._property_id(connection) != property_id:
                raise AccessAdministrationNotFound
            issued = self._issue_one_time_password(
                connection,
                owner=owner,
                user_id=user_id,
                reason=reason,
                reset_mfa=reset_mfa,
                credential=credential,
                request_id=audit_context.request_id,
            )
            if bool(issued[2]) and not reset_mfa:
                raise AccessAdministrationUnavailable
        return AdministrativeRecoveryView(
            user_id=user_id,
            password_changed=True,
            mfa_reset=bool(issued[2]),
            sessions_revoked=int(str(issued[5])),
            one_time_password=OneTimePasswordView(
                value=one_time_password, expires_at=cast(datetime, issued[1])
            ),
        )

    def _new_one_time_password(self) -> tuple[str, PasswordCredentialMaterial]:
        """A new one-time password and its Argon2id verifier, made before the transaction."""
        one_time_password = new_one_time_password()
        return one_time_password, self._password_service.hash_password(one_time_password)

    @staticmethod
    def _issue_one_time_password(
        connection: Connection,
        *,
        owner: UUID,
        user_id: UUID,
        reason: str,
        reset_mfa: bool,
        credential: PasswordCredentialMaterial,
        request_id: str,
    ) -> tuple[object, ...]:
        row = connection.execute(
            ISSUE_ONE_TIME_PASSWORD,
            (
                owner,
                user_id,
                correlation_id(request_id),
                reason,
                credential.verifier_encoding,
                credential.algorithm,
                json.dumps(dict(credential.work_factor_metadata)),
                reset_mfa,
            ),
        ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            raise AccessAdministrationUnavailable
        return tuple(row)


class PostgresAccessAdministrationScopeReader:
    """The `user_account` and `role_bundle` object scopes of the Owner (sub-slice L2b-2).

    Read through the Owner-only lists, so any other account gets no scope (fail closed). The
    session actor resolver (sub-slice L3a) adds them to the `identity.manage_access` grant on
    every request.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def object_scopes(self, actor_id: UUID) -> frozenset[ObjectScope]:
        try:
            # Login sub-slice L3a-2 review round 1: the resolver calls this on every Owner
            # request, so it has the resolver's timeouts.
            with psycopg.connect(
                self._database_url,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                options=STATEMENT_TIMEOUT_OPTION,
            ) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                accounts = connection.execute(
                    "SELECT actor_id::text FROM app.admin_accounts(%s)", (actor_id,)
                ).fetchall()
                bundles = connection.execute(
                    "SELECT role_bundle_id::text FROM app.admin_role_bundles(%s)", (actor_id,)
                ).fetchall()
        except psycopg.errors.InsufficientPrivilege as exc:
            if exc.diag.message_primary == "only the Owner administers accounts and role bundles":
                return frozenset()
            raise AccessAdministrationUnavailable from exc
        except psycopg.Error as exc:
            raise AccessAdministrationUnavailable from exc
        return frozenset(
            {ObjectScope(USER_ACCOUNT_OBJECT_TYPE, str(row[0])) for row in accounts}
            | {ObjectScope(ROLE_BUNDLE_OBJECT_TYPE, str(row[0])) for row in bundles}
        )


def with_administration_scopes(
    grants: frozenset[CapabilityGrant],
    scopes: frozenset[ObjectScope],
) -> frozenset[CapabilityGrant]:
    """Add the object scopes to the `identity.manage_access` grant only."""
    return frozenset(
        CapabilityGrant(
            capability=grant.capability,
            property_ids=grant.property_ids,
            object_scopes=grant.object_scopes | scopes,
        )
        if grant.capability == ACCESS_ADMIN_CAPABILITY
        else grant
        for grant in grants
    )
