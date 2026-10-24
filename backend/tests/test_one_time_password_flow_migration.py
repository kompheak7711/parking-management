"""Login sub-slice L4b: the one-time password through the flows, as the runtime role.

DL-058, DL-080 item 10, DL-081, API-096, API-099, SEC-011, SEC-014, SEC-075, TEST-130, TEST-131
(owner answers (a) to Q-2026-10-21-153, Q-2026-10-21-165 and Q-2026-10-23-180; technical points
Q-2026-10-24-185). The Owner creates and resets accounts through `PostgresAccessAdministrationFlow`
and the accounts sign in and change their password through `PostgresAuthenticationFlow`. One
throwaway database at head, shared by this module; each test uses its own accounts. Sign-in codes
are made for the time step of the database clock.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from property_rental.access_admin_flow import (
    ISSUE_ONE_TIME_PASSWORD,
    REPLACEMENT_LOCKS,
    PostgresAccessAdministrationFlow,
)
from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRejected,
    NewPasswordRejected,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.password_security import PasswordHashService, blocked_passwords
from test_access_admin_flow_migration import (
    AdminDatabase,
    audit_actions,
    context,
)
from test_access_admin_flow_migration import admin_database as admin_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_sign_in_code_migration import (
    KEY,
    PASSWORD,
    CodeDatabase,
    add_account,
    add_sign_in_code,
    code_for,
    fresh_step,
    lock_waits,
    read,
    username_key,
)

NEW_PASSWORD = "a long new password of my own"
BLOCKED = "Password1234567"
GIVEN = "identity.account.one_time_password_given"
CREDENTIAL_OF = "SELECT one_time_password_id FROM app.password_credentials WHERE actor_id = %s"
LIVE_SESSIONS_OF = (
    "SELECT count(*) FROM app.browser_sessions WHERE actor_id = %s AND revoked_at IS NULL"
)
REVOKED_REASONS_OF = (
    "SELECT revocation_reason FROM app.browser_sessions WHERE actor_id = %s "
    "AND revoked_at IS NOT NULL ORDER BY created_at"
)
ENROLLMENTS_OF = (
    "SELECT enrollment_state FROM app.totp_mfa_enrollments WHERE actor_id = %s ORDER BY created_at"
)
TRIES_OF = "SELECT try_kind FROM app.sign_in_wrong_tries WHERE username_digest = %s ORDER BY try_no"
ADD_RECOVERY_SET = (
    "INSERT INTO app.recovery_code_sets (set_id, actor_id, created_by_actor_id, provenance) "
    "VALUES (%s, %s, %s, %s)"
)
SET_ENDED = "SELECT invalidated_at IS NOT NULL FROM app.recovery_code_sets WHERE set_id = %s"
AGE_ONE_TIME_PASSWORD = (
    "UPDATE app.one_time_passwords SET issued_at = issued_at - %s::interval, "
    "expires_at = expires_at - %s::interval WHERE actor_id = %s"
)


def code_database(database: AdminDatabase) -> CodeDatabase:
    return CodeDatabase(database.owner_url, database.runtime_url)


def auth_flow(database: AdminDatabase) -> PostgresAuthenticationFlow:
    return PostgresAuthenticationFlow(
        database.runtime_url,
        totp_protection_key=KEY,
        password_blocklist=blocked_passwords([BLOCKED]),
    )


def sign_in(flow: PostgresAuthenticationFlow, username: str, password: str) -> Any:
    return flow.login(
        username=username, password=password, request_source="front-desk", request_id="l4b"
    )


def change(flow: PostgresAuthenticationFlow, token: str, password: str) -> Any:
    return flow.change_password(preauth_token=token, new_password=password, request_id="l4b")


def new_account(
    database: AdminDatabase, name: str, account_class: str = "staff"
) -> tuple[Any, str]:
    """An account the Owner creates, and its username."""
    username = f"{name}-{uuid.uuid4().hex[:8]}"
    account = PostgresAccessAdministrationFlow(database.runtime_url).create_user(
        property_id=database.property_id,
        username=username,
        display_name=f"{name} Display",
        audit_name=f"{name} Audit",
        account_class="manager" if account_class == "manager" else "staff",
        audit_context=context(database.owner, f"create-{username}"),
    )
    return account, username


def age(database: AdminDatabase, actor_id: object, by: str) -> None:
    """Moves the account's one-time passwords back by `by`, triggers off for that update."""
    with psycopg.connect(database.owner_url) as connection:
        connection.execute("ALTER TABLE app.one_time_passwords DISABLE TRIGGER USER")
        connection.execute(AGE_ONE_TIME_PASSWORD, (by, by, actor_id))
        connection.execute("ALTER TABLE app.one_time_passwords ENABLE TRIGGER USER")
        connection.commit()


def test_a_new_account_signs_in_with_its_first_one_time_password_and_must_change_it(
    admin_database: AdminDatabase,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TEST-130, owner answer (a) to Q-2026-10-21-153: a new Staff account gets its first
    password as a one-time password for 24 hours, answered once; it signs in to the password
    change only (no session); a new password against the rule is refused and the step stays
    open; the right one replaces it, ends the step and signs in; the one-time password then no
    longer works and the new one does. No password is logged."""
    caplog.set_level(logging.DEBUG)
    flow = auth_flow(admin_database)
    account, username = new_account(admin_database, "firstaccount")
    assert account.one_time_password is not None
    one_time_password = account.one_time_password.value
    left = account.one_time_password.expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=58) < left <= timedelta(hours=24, minutes=1)
    assert one_time_password not in repr(account)
    assert GIVEN in audit_actions(admin_database, f"create-{username}")

    started = sign_in(flow, username, one_time_password)
    assert started.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED
    assert started.session is None and started.session_token is None
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, account.user_id) == [(0,)]

    for refused in (
        "too short pass",
        BLOCKED.upper(),
        "FIRSTACCOUNT display",
        "firstaccount Audit",
        username.upper(),
        one_time_password,
        one_time_password.upper(),
        one_time_password.replace("-", ""),
        one_time_password.replace("-", " "),
    ):
        with pytest.raises(NewPasswordRejected):
            change(flow, started.preauth_token, refused)
    changed = change(flow, started.preauth_token, NEW_PASSWORD)
    assert changed.phase is AuthenticationPhase.AUTHENTICATED
    assert changed.session is not None and changed.session.actor_id == str(account.user_id)
    with pytest.raises(AuthenticationRejected):
        change(flow, started.preauth_token, "another long new password")
    assert read(code_database(admin_database), CREDENTIAL_OF, account.user_id) == [(None,)]

    with pytest.raises(AuthenticationRejected):
        sign_in(flow, username, one_time_password)
    assert sign_in(flow, username, NEW_PASSWORD).phase is AuthenticationPhase.AUTHENTICATED
    logged = caplog.text
    for secret in (one_time_password, NEW_PASSWORD, started.preauth_token):
        assert secret not in logged


def test_the_owners_reset_ends_every_session_and_keeps_or_resets_the_sign_in_code(
    admin_database: AdminDatabase,
) -> None:
    """TEST-131, DL-080 item 10, owner answer (a) to Q-2026-10-21-165: the Owner's reset of a
    Manager ends every session of the account; the old password no longer signs in; the
    one-time password leads to the password change and then to the sign-in code the account
    kept; with "also reset MFA" the sign-in code ends and the change leads to its set-up."""
    flow = auth_flow(admin_database)
    admin = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    database = code_database(admin_database)
    manager = add_account(database, f"l4b-manager-{uuid.uuid4().hex[:8]}")
    signed_in = sign_in(flow, manager.username, PASSWORD)
    assert signed_in.phase is AuthenticationPhase.MFA_REQUIRED
    done = flow.complete_mfa(
        preauth_token=signed_in.preauth_token,
        method="totp",
        code=code_for(manager, fresh_step(database)),
        request_id="l4b",
    )
    assert done.session_token is not None

    reset = admin.administratively_recover_user(
        user_id=manager.actor_id,
        property_id=admin_database.property_id,
        reset_mfa=False,
        reason="Forgot the password",
        audit_context=context(admin_database.owner, "reset-keep-code"),
    )
    assert (reset.password_changed, reset.mfa_reset, reset.sessions_revoked) == (True, False, 1)
    assert GIVEN in audit_actions(admin_database, "reset-keep-code")
    assert read(database, LIVE_SESSIONS_OF, manager.actor_id) == [(0,)]
    assert read(database, REVOKED_REASONS_OF, manager.actor_id) == [("password_reset",)]
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=done.session_token, request_id="l4b")
    with pytest.raises(AuthenticationRejected):
        sign_in(flow, manager.username, PASSWORD)

    started = sign_in(flow, manager.username, reset.one_time_password.value)
    assert started.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED
    changed = change(flow, started.preauth_token, NEW_PASSWORD)
    assert changed.phase is AuthenticationPhase.MFA_REQUIRED and changed.session is None
    assert read(database, ENROLLMENTS_OF, manager.actor_id) == [("active",)]

    again = admin.administratively_recover_user(
        user_id=manager.actor_id,
        property_id=admin_database.property_id,
        reset_mfa=True,
        reason="Lost the phone",
        audit_context=context(admin_database.owner),
    )
    assert again.mfa_reset is True
    assert read(database, ENROLLMENTS_OF, manager.actor_id) == [("disabled",)]
    with pytest.raises(AuthenticationRejected):
        sign_in(flow, manager.username, NEW_PASSWORD)
    started = sign_in(flow, manager.username, again.one_time_password.value)
    changed = change(flow, started.preauth_token, "yet another long password")
    assert changed.phase is AuthenticationPhase.MFA_ENROLLMENT_REQUIRED


def test_a_one_time_password_works_for_24_hours_and_then_counts_as_a_wrong_try(
    admin_database: AdminDatabase,
) -> None:
    """Q-2026-10-24-185: just before its 24 hours end the one-time password still signs in to
    the change; after them it gets the generic refusal and counts as one wrong try, and a
    change step opened before the end is refused too."""
    flow = auth_flow(admin_database)
    account, username = new_account(admin_database, "expiry")
    assert account.one_time_password is not None
    one_time_password = account.one_time_password.value

    age(admin_database, account.user_id, "23 hours 59 minutes")
    started = sign_in(flow, username, one_time_password)
    assert started.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED
    key = username_key(username)
    assert read(code_database(admin_database), TRIES_OF, key) == []

    age(admin_database, account.user_id, "2 minutes")
    with pytest.raises(AuthenticationRejected):
        sign_in(flow, username, one_time_password)
    assert read(code_database(admin_database), TRIES_OF, key) == [("password",)]
    with pytest.raises(AuthenticationRejected):
        change(flow, started.preauth_token, NEW_PASSWORD)
    assert read(code_database(admin_database), CREDENTIAL_OF, account.user_id) != [(None,)]


def test_turning_a_staff_accounts_mfa_off_gives_a_one_time_password(
    admin_database: AdminDatabase,
) -> None:
    """Owner answer (a) to Q-2026-10-23-180: turning off the MFA a Staff account had to use ends
    its sign-in code and gives it a one-time password; after the change the account signs in
    without a sign-in code. Turning MFA on gives none."""
    flow = auth_flow(admin_database)
    admin = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    account, username = new_account(admin_database, "mfa-off")
    required = admin.update_user(
        user_id=account.user_id,
        property_id=admin_database.property_id,
        expected_version=account.version,
        display_name=None,
        audit_name=None,
        lifecycle_state=None,
        mfa_policy_class="required",
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(admin_database.owner),
    )
    assert required.one_time_password is None
    set_id = uuid.uuid4()
    with psycopg.connect(admin_database.owner_url) as connection:
        add_sign_in_code(connection, account.user_id)
        connection.execute(ADD_RECOVERY_SET, (set_id, account.user_id, account.user_id, "l4b"))
        connection.commit()

    turned_off = admin.update_user(
        user_id=account.user_id,
        property_id=admin_database.property_id,
        expected_version=required.version,
        display_name=None,
        audit_name=None,
        lifecycle_state=None,
        mfa_policy_class="optional",
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(admin_database.owner, f"mfa-off-{username}"),
    )
    assert turned_off.mfa_policy_class == "optional"
    assert turned_off.one_time_password is not None
    assert GIVEN in audit_actions(admin_database, f"mfa-off-{username}")
    assert read(code_database(admin_database), ENROLLMENTS_OF, account.user_id) == [("disabled",)]
    # Review round 1: the live recovery codes end in the same step (Q-2026-10-23-180 (a)).
    assert read(code_database(admin_database), SET_ENDED, set_id) == [(True,)]
    started = sign_in(flow, username, turned_off.one_time_password.value)
    changed = change(flow, started.preauth_token, NEW_PASSWORD)
    assert changed.phase is AuthenticationPhase.AUTHENTICATED


def test_a_reset_staff_account_with_its_own_sign_in_code_still_needs_the_code(
    admin_database: AdminDatabase,
) -> None:
    """Review round 2: a Staff account whose MFA is optional but which set up a sign-in code
    keeps the code after a reset without "also reset MFA", so the change leads to the code and
    never straight to a session."""
    flow = auth_flow(admin_database)
    admin = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    account, username = new_account(admin_database, "own-code")
    assert account.mfa_policy_class == "optional"
    with psycopg.connect(admin_database.owner_url) as connection:
        add_sign_in_code(connection, account.user_id)
        connection.commit()

    reset = admin.administratively_recover_user(
        user_id=account.user_id,
        property_id=admin_database.property_id,
        reset_mfa=False,
        reason="Forgot the password",
        audit_context=context(admin_database.owner),
    )
    assert reset.mfa_reset is False
    started = sign_in(flow, username, reset.one_time_password.value)
    assert started.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED
    changed = change(flow, started.preauth_token, NEW_PASSWORD)
    assert changed.phase is AuthenticationPhase.MFA_REQUIRED and changed.session is None
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, account.user_id) == [(0,)]


def changed_staff(database: AdminDatabase) -> tuple[uuid.UUID, str]:
    """A Staff account that has changed its first password to `NEW_PASSWORD`."""
    flow = auth_flow(database)
    account, username = new_account(database, "race")
    assert account.one_time_password is not None
    started = sign_in(flow, username, account.one_time_password.value)
    change(flow, started.preauth_token, NEW_PASSWORD)
    return account.user_id, username


def reset_while_waiting(database: AdminDatabase, actor_id: uuid.UUID, call: Any) -> list[object]:
    """Holds the replacement locks as the Owner's reset does, starts `call` in a thread, waits
    until it waits for the lock, then resets the password in the same transaction; answers what
    the call returned or raised."""
    outcome: list[object] = []

    def run() -> None:
        try:
            outcome.append(call())
        except Exception as exc:  # the test reads what the thread raised
            outcome.append(exc)

    credential = PasswordHashService().hash_password("a racing one-time password")
    with psycopg.connect(database.runtime_url) as connection:
        connection.execute(REPLACEMENT_LOCKS, (actor_id, actor_id))
        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.monotonic() + 30
        while lock_waits(code_database(database)) < 1:
            assert time.monotonic() < deadline and worker.is_alive()
            time.sleep(0.05)
        connection.execute(
            ISSUE_ONE_TIME_PASSWORD,
            (
                database.owner,
                actor_id,
                uuid.uuid4(),
                "Race",
                credential.verifier_encoding,
                credential.algorithm,
                json.dumps(dict(credential.work_factor_metadata)),
                False,
            ),
        )
        connection.commit()
    worker.join(30)
    assert not worker.is_alive()
    return outcome


def test_a_sign_in_or_reauthentication_that_meets_a_reset_waits_and_is_refused(
    admin_database: AdminDatabase,
) -> None:
    """The L3a-1 and L3d-1 bindings (Q-2026-10-24-185 point 5), with the real statements: a
    session write takes the account's password lock shared first, and the reset takes it
    exclusive first, so a sign-in or a reauthentication whose password was checked before the
    reset waits for it and is then refused; no session of the old password is left."""
    flow = auth_flow(admin_database)
    actor_id, username = changed_staff(admin_database)
    outcome = reset_while_waiting(
        admin_database, actor_id, lambda: sign_in(flow, username, NEW_PASSWORD)
    )
    assert len(outcome) == 1 and isinstance(outcome[0], AuthenticationRejected)
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, actor_id) == [(0,)]

    actor_id, username = changed_staff(admin_database)
    session = sign_in(flow, username, NEW_PASSWORD).session_token
    outcome = reset_while_waiting(
        admin_database,
        actor_id,
        lambda: flow.reauthenticate(
            session_token=session,
            password=NEW_PASSWORD,
            second_factor_method=None,
            second_factor_code=None,
            request_id="l4b",
        ),
    )
    assert len(outcome) == 1 and isinstance(outcome[0], AuthenticationRejected)
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, actor_id) == [(0,)]


def test_a_forced_change_that_meets_a_reset_waits_and_is_refused(
    admin_database: AdminDatabase,
) -> None:
    """Review round 1 (security note 8): a forced change whose step was opened before a reset
    waits for the reset's lock and is then refused, because a newer one-time password was
    given; the change step's password is never stored and no session is made."""
    flow = auth_flow(admin_database)
    account, username = new_account(admin_database, "change-race")
    assert account.one_time_password is not None
    started = sign_in(flow, username, account.one_time_password.value)
    outcome = reset_while_waiting(
        admin_database,
        account.user_id,
        lambda: change(flow, started.preauth_token, NEW_PASSWORD),
    )
    assert len(outcome) == 1 and isinstance(outcome[0], AuthenticationRejected)
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, account.user_id) == [(0,)]
    with pytest.raises(AuthenticationRejected):
        sign_in(flow, username, NEW_PASSWORD)


def test_a_sign_in_code_set_up_that_meets_a_reset_waits_and_is_refused(
    admin_database: AdminDatabase,
) -> None:
    """Review round 3: starting a sign-in code set-up takes the account's password lock shared
    like every other sign-in write, so a set-up from before a reset waits for it and is then
    refused; no pending sign-in code is written."""
    flow = auth_flow(admin_database)
    account, username = new_account(admin_database, "setup-race", "manager")
    assert account.one_time_password is not None
    started = sign_in(flow, username, account.one_time_password.value)
    changed = change(flow, started.preauth_token, NEW_PASSWORD)
    assert changed.phase is AuthenticationPhase.MFA_ENROLLMENT_REQUIRED
    outcome = reset_while_waiting(
        admin_database,
        account.user_id,
        lambda: flow.begin_mfa_enrollment(preauth_token=changed.preauth_token, request_id="l4b"),
    )
    assert len(outcome) == 1 and isinstance(outcome[0], AuthenticationRejected)
    assert read(code_database(admin_database), ENROLLMENTS_OF, account.user_id) == []


def test_a_change_step_of_an_account_disabled_meanwhile_is_refused(
    admin_database: AdminDatabase,
) -> None:
    """Review round 1: an account the Owner disables while its change step is open cannot
    finish the change; its one-time password stays unchanged and no session is made."""
    flow = auth_flow(admin_database)
    admin = PostgresAccessAdministrationFlow(admin_database.runtime_url)
    account, username = new_account(admin_database, "disabled-step")
    assert account.one_time_password is not None
    started = sign_in(flow, username, account.one_time_password.value)
    admin.update_user(
        user_id=account.user_id,
        property_id=admin_database.property_id,
        expected_version=account.version,
        display_name=None,
        audit_name=None,
        lifecycle_state="disabled",
        mfa_policy_class=None,
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(admin_database.owner),
    )
    with pytest.raises(AuthenticationRejected):
        change(flow, started.preauth_token, NEW_PASSWORD)
    assert read(code_database(admin_database), CREDENTIAL_OF, account.user_id) != [(None,)]
    assert read(code_database(admin_database), LIVE_SESSIONS_OF, account.user_id) == [(0,)]
