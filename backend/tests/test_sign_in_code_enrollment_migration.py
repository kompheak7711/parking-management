"""Login sub-slice L3c-2b: setting up a sign-in code at sign-in.

DL-056, SEC-013, API-096, UI-110, TEST-128, DB-AUTH-003, DB-AUTH-004 (migration `20270131_188`).
One throwaway database at head; accounts and real Argon2id credentials are written as the table
owner, and every sign-in runs as the runtime role through `PostgresAuthenticationFlow`. Each test
uses its own accounts and request sources, so the order of the tests does not matter. Sign-in
codes are made for the time step of the database clock, never of the test machine.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from psycopg import errors
from pydantic import SecretStr

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.local_authentication import verifier_digest
from property_rental.password_security import PasswordHashService
from property_rental.runtime_secrets import derive_totp_key_identifier
from property_rental.session_actor import PostgresSessionActorResolver
from property_rental.settings import Settings
from property_rental.totp_qr import provisioning_qr_svg
from property_rental.totp_security import TotpSecret, TotpService
from test_sign_in_code_migration import (
    CHALLENGES_OF,
    CLEARS_OF,
    CREDENTIAL_OF,
    KEY,
    ORIGIN,
    PASSWORD,
    PROOFS_OF,
    SESSIONS_OF,
    TRIES_OF,
    TURN_CODE_OFF,
    USED_STEPS_OF,
    Account,
    CodeDatabase,
    add_account,
    add_sign_in_code,
    challenge_token,
    change_for,
    digest,
    fresh_step,
    lock_waits,
    read,
    request_with,
    username_key,
)
from test_sign_in_code_migration import code_database as code_database
from test_sign_in_code_migration import migrated_database_url as migrated_database_url

REVISION = "20270131_188"
PREVIOUS = "20270130_187"
PROVENANCE = "login-slice-l3c-2b-test"
CODES_OF = (
    "SELECT enrollment_id, enrollment_state, key_identifier, protection_algorithm, "
    "secret_ciphertext, created_by_actor_id, provenance, activated_by_actor_id, "
    "activation_provenance, disabled_by_actor_id, disablement_provenance "
    "FROM app.totp_mfa_enrollments WHERE actor_id = %s ORDER BY created_at"
)
STARTS_OF = (
    "SELECT start.enrollment_id, challenge.token_verifier "
    "FROM app.sign_in_code_enrollment_starts AS start "
    "JOIN app.sign_in_mfa_challenges AS challenge ON challenge.challenge_id = start.challenge_id "
    "WHERE start.actor_id = %s ORDER BY start.started_at"
)
ADD_PENDING_CODE = (
    "INSERT INTO app.totp_mfa_enrollments(enrollment_id,actor_id,secret_ciphertext,secret_nonce,"
    "key_identifier,protection_algorithm,totp_algorithm,created_by_actor_id,provenance) "
    f"VALUES (%s,%s,%s,%s,'l3c-2b-test-key','aes-256-gcm','sha1',%s,'{PROVENANCE}')"
)
ADD_START = (
    "INSERT INTO app.sign_in_code_enrollment_starts (challenge_id, actor_id, enrollment_id) "
    "SELECT challenge.challenge_id, %s, %s FROM app.sign_in_mfa_challenges AS challenge "
    "WHERE challenge.token_verifier = %s"
)
REAUTHENTICATIONS_OF = (
    "SELECT method, enrollment_id, time_step FROM app.browser_session_reauthentications "
    "WHERE actor_id = %s ORDER BY reauthenticated_at"
)


def enrollment_token(flow: PostgresAuthenticationFlow, account: Account, source: str) -> str:
    result = flow.login(
        username=account.username, password=PASSWORD, request_source=source, request_id="l3c-2b"
    )
    assert result.phase is AuthenticationPhase.MFA_ENROLLMENT_REQUIRED
    assert result.session is None and result.session_token is None
    assert result.preauth_token is not None
    return result.preauth_token


def begin(flow: PostgresAuthenticationFlow, token: str) -> TotpSecret:
    """Begin the enrollment and read the secret from the provisioning link."""
    link = urlsplit(
        flow.begin_mfa_enrollment(preauth_token=token, request_id="l3c-2b").provisioning_uri
    )
    return TotpSecret.from_base32(parse_qs(link.query)["secret"][0])


def code_of(secret: TotpSecret, step: int) -> str:
    return TotpService().generate_code(secret, at_time=step * 30)


def wrong_code_of(secret: TotpSecret, step: int) -> str:
    right = {code_of(secret, step), code_of(secret, step - 1)}
    return next(code for code in ("000000", "111111", "222222") if code not in right)


def new_account(database: CodeDatabase, username: str, **kwargs: Any) -> Account:
    return add_account(database, username, sign_in_code=False, **kwargs)


def add_pending_code(
    connection: psycopg.Connection[tuple[Any, ...]], actor_id: uuid.UUID
) -> uuid.UUID:
    """A pending sign-in code with stand-in protected material (not committed)."""
    enrollment_id = uuid.uuid4()
    connection.execute(
        ADD_PENDING_CODE,
        (enrollment_id, actor_id, bytes(36), uuid.uuid4().bytes[:12], actor_id),
    )
    return enrollment_id


def assert_nothing_started(database: CodeDatabase, account: Account) -> None:
    assert read(database, CODES_OF, account.actor_id) == []
    assert read(database, STARTS_OF, account.actor_id) == []
    assert read(database, SESSIONS_OF, account.actor_id) == []


def test_an_account_without_a_sign_in_code_sets_one_up_and_its_first_right_code_makes_a_session(
    code_database: CodeDatabase,
) -> None:
    """TEST-128, DL-056, UI-110: the Owner, a Manager and a Staff account with MFA `required` and
    no sign-in code get `mfa_enrollment_required`; beginning the enrollment writes one `pending`
    sign-in code protected with the key file (the derived key identifier, no secret in the
    clear) and one start of the challenge, and answers the provisioning link; after one wrong
    code, the first right code (the previous step) activates the code, makes a session with
    `mfa_assurance` `totp` and one proof and clears the count, and the session read and the actor
    resolver accept it. The next sign-in asks for the code and the current step completes it."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    for username, account_class in (
        ("l3c-2b.owner", "owner"),
        ("l3c-2b.manager", "manager"),
        ("l3c-2b.staff", "staff"),
    ):
        account = new_account(code_database, username, account_class=account_class)
        preauth = enrollment_token(flow, account, f"{username}-desk")
        result = flow.begin_mfa_enrollment(preauth_token=preauth, request_id="l3c-2b")
        link = urlsplit(result.provisioning_uri)
        assert unquote(link.path) == f"/CHETANA Residence:{username}"
        query = parse_qs(link.query)
        assert (query["issuer"], query["digits"], query["period"]) == (
            ["CHETANA Residence"],
            ["6"],
            ["30"],
        )
        secret = TotpSecret.from_base32(query["secret"][0])
        codes = read(code_database, CODES_OF, account.actor_id)
        assert [row[1:4] + row[5:9] for row in codes] == [
            (
                "pending",
                derive_totp_key_identifier(KEY),
                "aes-256-gcm",
                account.actor_id,
                "auth-mfa-enrollment",
                None,
                None,
            )
        ]
        assert secret.get_bytes() not in bytes(codes[0][4])
        enrollment_id = codes[0][0]
        assert [
            (row[0], bytes(row[1])) for row in read(code_database, STARTS_OF, account.actor_id)
        ] == [(enrollment_id, digest(preauth))]
        assert read(code_database, SESSIONS_OF, account.actor_id) == []
        step = fresh_step(code_database)
        with pytest.raises(AuthenticationRejected):
            flow.confirm_mfa_enrollment(
                preauth_token=preauth, code=wrong_code_of(secret, step), request_id="l3c-2b"
            )
        done = flow.confirm_mfa_enrollment(
            preauth_token=preauth, code=code_of(secret, step - 1), request_id="l3c-2b"
        )
        assert done.phase is AuthenticationPhase.AUTHENTICATED
        assert done.session is not None and done.session_token is not None
        assert done.csrf_token and done.csrf_token != done.session_token
        assert (done.session.actor_id, done.session.mfa_assurance) == (
            str(account.actor_id),
            "totp",
        )
        assert [
            (row[1], row[7], row[8]) for row in read(code_database, CODES_OF, account.actor_id)
        ] == [("active", account.actor_id, "auth-mfa-enrollment")]
        assert read(code_database, USED_STEPS_OF, enrollment_id) == [(step - 1,)]
        assert read(code_database, PROOFS_OF, account.actor_id) == [("totp", enrollment_id)]
        # Login sub-slice L3d-2 (Q-2026-10-24-184): the sign-in also reauthenticates the new
        # session with the step it used, in the same transaction, and answers its cookie.
        assert done.reauthentication_token and done.session.reauthenticated_at is not None
        assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == [
            ("totp", enrollment_id, step - 1)
        ]
        assert [
            (bytes(row[1]), row[2]) for row in read(code_database, SESSIONS_OF, account.actor_id)
        ] == [(digest(done.session_token), "auth-mfa-enrollment")]
        assert [row[1:3] for row in read(code_database, CHALLENGES_OF, account.actor_id)] == [
            ("enrollment", True)
        ]
        assert read(code_database, CLEARS_OF, username_key(username)) == [(1,)]
        assert flow.inspect_session(
            session_token=done.session_token, request_id="r"
        ).mfa_assurance == ("totp")
        actor = resolver(request_with(f"__Host-prm_session={done.session_token}"))
        assert actor is not None and actor.actor_id == str(account.actor_id)
        enrolled = Account(account.actor_id, username, secret, enrollment_id)
        again = challenge_token(flow, enrolled, f"{username}-desk")
        later = flow.complete_mfa(
            preauth_token=again, method="totp", code=code_of(secret, step), request_id="l3c-2b"
        )
        assert later.session is not None and later.session.mfa_assurance == "totp"


def test_wrong_codes_at_the_set_up_count_as_wrong_tries_and_a_right_code_waits(
    code_database: CodeDatabase,
) -> None:
    """Q-2026-10-21-154 (a): a wrong first code is a wrong try of kind `sign_in_code`; the 3rd
    starts the 5-minute wait (429), and the right code during the wait is refused with 429; the
    sign-in code stays pending and no session is made."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.wrong")
    preauth = enrollment_token(flow, account, "l3c-2b-wrong")
    secret = begin(flow, preauth)
    step = fresh_step(code_database)
    for _ in range(2):
        with pytest.raises(AuthenticationRejected):
            flow.confirm_mfa_enrollment(
                preauth_token=preauth, code=wrong_code_of(secret, step), request_id="w"
            )
    with pytest.raises(AuthenticationRateLimited) as started:
        flow.confirm_mfa_enrollment(
            preauth_token=preauth, code=wrong_code_of(secret, step), request_id="w"
        )
    assert started.value.retry_after_seconds == 300
    with pytest.raises(AuthenticationRateLimited):
        flow.confirm_mfa_enrollment(
            preauth_token=preauth, code=code_of(secret, step), request_id="w"
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == [
        ("sign_in_code",),
        ("sign_in_code",),
        ("sign_in_code",),
    ]
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == ["pending"]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(0,)]


def test_a_challenge_starts_once_and_a_later_sign_in_replaces_an_unconfirmed_code(
    code_database: CodeDatabase,
) -> None:
    """One start per `enrollment` challenge: beginning again with the same token is refused. A
    later sign-in's start turns the unconfirmed code off (by the account itself, provenance
    `auth-mfa-enrollment-replaced`), so the first token and its secret no longer confirm (no
    wrong try is counted); the new code confirms."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.again")
    first = enrollment_token(flow, account, "l3c-2b-again")
    first_secret = begin(flow, first)
    with pytest.raises(AuthenticationRejected):
        flow.begin_mfa_enrollment(preauth_token=first, request_id="a")
    assert len(read(code_database, CODES_OF, account.actor_id)) == 1
    second = enrollment_token(flow, account, "l3c-2b-again")
    second_secret = begin(flow, second)
    codes = read(code_database, CODES_OF, account.actor_id)
    assert [(row[1], row[9], row[10]) for row in codes] == [
        ("disabled", account.actor_id, "auth-mfa-enrollment-replaced"),
        ("pending", None, None),
    ]
    step = fresh_step(code_database)
    with pytest.raises(AuthenticationRejected):
        flow.confirm_mfa_enrollment(
            preauth_token=first, code=code_of(first_secret, step), request_id="a"
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == []
    done = flow.confirm_mfa_enrollment(
        preauth_token=second, code=code_of(second_secret, step), request_id="a"
    )
    assert done.session is not None
    assert read(code_database, PROOFS_OF, account.actor_id) == [("totp", codes[1][0])]
    with pytest.raises(AuthenticationRejected):
        flow.confirm_mfa_enrollment(
            preauth_token=second, code=code_of(second_secret, step), request_id="a"
        )
    assert len(read(code_database, SESSIONS_OF, account.actor_id)) == 1


@pytest.mark.parametrize("case", ["code", "optional", "new_code", "disabled", "expired", "long"])
def test_only_an_open_enrollment_challenge_of_an_account_that_still_needs_a_code_starts(
    code_database: CodeDatabase,
    case: str,
) -> None:
    """The L3c-2a binding: beginning is refused with the generic rejection and writes nothing
    for the token of a `challenge` (the account has a sign-in code), for an account whose MFA
    became `optional`, that got a sign-in code meanwhile or was disabled, for an `enrollment`
    challenge made 6 minutes ago by the database clock and for a token over 128 characters (whose
    digest is stored as an open `enrollment` challenge, review round 1)."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    username = f"l3c-2b.refused-{case}"
    if case == "code":
        account = add_account(code_database, username)
        token = challenge_token(flow, account, "l3c-2b-refused")
        before = read(
            code_database,
            "SELECT count(*) FROM app.totp_mfa_enrollments WHERE actor_id = %s",
            account.actor_id,
        )
        with pytest.raises(AuthenticationRejected):
            flow.begin_mfa_enrollment(preauth_token=token, request_id="n")
        assert (
            read(
                code_database,
                "SELECT count(*) FROM app.totp_mfa_enrollments WHERE actor_id = %s",
                account.actor_id,
            )
            == before
        )
        assert read(code_database, STARTS_OF, account.actor_id) == []
        return
    account = new_account(code_database, username, account_class="staff")
    token = enrollment_token(flow, account, "l3c-2b-refused")
    with psycopg.connect(code_database.owner_url) as connection:
        if case == "optional":
            connection.execute(
                "UPDATE app.user_accounts SET mfa_policy_class = 'optional' WHERE actor_id = %s",
                (account.actor_id,),
            )
        elif case == "new_code":
            add_sign_in_code(connection, account.actor_id)
        elif case == "disabled":
            connection.execute(
                "UPDATE app.user_accounts SET lifecycle_state = 'disabled' WHERE actor_id = %s",
                (account.actor_id,),
            )
        elif case == "expired":
            verifier = read(code_database, CREDENTIAL_OF, account.actor_id)[0][0]
            stored = read(code_database, CHALLENGES_OF, account.actor_id)[0]
            token = "e" * 43
            connection.execute(
                "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
                "purpose, password_verifier_digest, username_digest, source_digest, created_at, "
                "expires_at) SELECT %s, %s, %s, 'enrollment', %s, %s, %s, moment.at, "
                "moment.at + interval '5 minutes' "
                "FROM (SELECT statement_timestamp() - interval '6 minutes' AS at) AS moment",
                (
                    uuid.uuid4(),
                    account.actor_id,
                    digest(token),
                    verifier_digest(str(verifier)),
                    bytes(stored[4]),
                    bytes(stored[5]),
                ),
            )
        else:
            stored = read(code_database, CHALLENGES_OF, account.actor_id)[0]
            token = "t" * 129
            connection.execute(
                "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
                "purpose, password_verifier_digest, username_digest, source_digest) "
                "VALUES (%s, %s, %s, 'enrollment', %s, %s, %s)",
                (
                    uuid.uuid4(),
                    account.actor_id,
                    digest(token),
                    bytes(stored[3]),
                    bytes(stored[4]),
                    bytes(stored[5]),
                ),
            )
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.begin_mfa_enrollment(preauth_token=token, request_id="n")
    codes = read(code_database, CODES_OF, account.actor_id)
    assert [row[1] for row in codes] == (["active"] if case == "new_code" else [])
    assert read(code_database, STARTS_OF, account.actor_id) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == []


def test_a_sign_in_from_before_a_password_reset_starts_nothing(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (security; reviewer's set-up): after a password reset, the `enrollment`
    token of a sign-in with the old password is refused at the start, so it cannot turn off the
    code that a sign-in with the new password started; nothing is replaced or written."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.reset-begin")
    old_token = enrollment_token(flow, account, "l3c-2b-reset")
    new_password = "an entirely different passphrase"
    replacement = PasswordHashService().hash_password(new_password)
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.password_credentials SET verifier_encoding = %s, "
            "changed_by_actor_id = %s, provenance = 'l3c-2b-reset-test' WHERE actor_id = %s",
            (replacement.verifier_encoding, account.actor_id, account.actor_id),
        )
        connection.commit()
    result = flow.login(
        username=account.username,
        password=new_password,
        request_source="l3c-2b-reset",
        request_id="b",
    )
    assert result.preauth_token is not None
    begin(flow, result.preauth_token)
    with pytest.raises(AuthenticationRejected):
        flow.begin_mfa_enrollment(preauth_token=old_token, request_id="b")
    codes = read(code_database, CODES_OF, account.actor_id)
    assert [(row[1], row[10]) for row in codes] == [("pending", None)]
    assert [bytes(row[1]) for row in read(code_database, STARTS_OF, account.actor_id)] == [
        digest(result.preauth_token)
    ]


def test_a_start_during_a_wait_answers_429_and_writes_nothing(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (reviewer's set-up): during a wait for the stored username, beginning
    answers 429 with the seconds left (Q-2026-10-23-179 point 4) and writes nothing."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.begin-wait")
    preauth = enrollment_token(flow, account, "l3c-2b-begin-wait")
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[0]
    with psycopg.connect(code_database.runtime_url) as connection:
        for _ in range(3):
            connection.execute(
                "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')",
                (bytes(stored[4]), bytes(stored[5])),
            )
            connection.commit()
    with pytest.raises(AuthenticationRateLimited) as waiting:
        flow.begin_mfa_enrollment(preauth_token=preauth, request_id="w")
    assert waiting.value.retry_after_seconds == 300
    assert_nothing_started(code_database, account)


def test_two_parallel_starts_of_one_challenge_start_it_once(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (reviewer's set-up): two starts of one `enrollment` challenge at the same
    moment, while the table owner holds the challenge row, wait for each other; one starts the
    code and the other gets the generic rejection (not an unavailable answer)."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.parallel-begin")
    preauth = enrollment_token(flow, account, "l3c-2b-parallel-begin")
    outcomes: list[str] = []

    def start() -> None:
        try:
            flow.begin_mfa_enrollment(preauth_token=preauth, request_id="p")
            outcomes.append("started")
        except AuthenticationRejected:
            outcomes.append("rejected")
        except AuthenticationUnavailable:
            outcomes.append("unavailable")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.sign_in_mfa_challenges WHERE token_verifier = %s FOR UPDATE",
            (digest(preauth),),
        )
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 2:
            time.sleep(0.05)
        waited = lock_waits(code_database)
        holder.commit()
    assert waited >= 2
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(outcomes) == ["rejected", "started"]
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == ["pending"]
    assert len(read(code_database, STARTS_OF, account.actor_id)) == 1


def test_two_parallel_starts_of_two_challenges_of_one_account_start_one_code(
    code_database: CodeDatabase,
) -> None:
    """Review round 2 (reviewer's set-up): two sign-ins of one account start at the same moment,
    while the table owner holds the account row; the first waits at its new code's account key
    and the second at the one-live index behind the first's uncommitted code (review round 3);
    when the first commits, the second meets that index and gets the generic rejection (not an
    unavailable answer); one pending code, no code turned off and one start."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.parallel-two")
    tokens = [enrollment_token(flow, account, "l3c-2b-parallel-two") for _ in range(2)]
    outcomes: list[str] = []

    def start(token: str) -> None:
        try:
            flow.begin_mfa_enrollment(preauth_token=token, request_id="p")
            outcomes.append("started")
        except AuthenticationRejected:
            outcomes.append("rejected")
        except AuthenticationUnavailable:
            outcomes.append("unavailable")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.user_accounts WHERE actor_id = %s FOR UPDATE", (account.actor_id,)
        )
        threads = [threading.Thread(target=start, args=(token,)) for token in tokens]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 2:
            time.sleep(0.05)
        waited = lock_waits(code_database)
        holder.commit()
    assert waited >= 2
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(outcomes) == ["rejected", "started"]
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == ["pending"]
    assert len(read(code_database, STARTS_OF, account.actor_id)) == 1


def test_a_started_code_is_not_confirmed_once_mfa_is_optional(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (reviewer's set-up): MFA turned off while a start commits can leave the
    started code pending (the state is written by hand); its right first code is refused, so
    the code stays pending and nothing is written."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.optional-start", account_class="staff")
    preauth = enrollment_token(flow, account, "l3c-2b-optional-start")
    secret = begin(flow, preauth)
    enrollment_id = read(code_database, CODES_OF, account.actor_id)[0][0]
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET mfa_policy_class = 'optional' WHERE actor_id = %s",
            (account.actor_id,),
        )
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.confirm_mfa_enrollment(
            preauth_token=preauth, code=code_of(secret, fresh_step(code_database)), request_id="o"
        )
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == ["pending"]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []
    assert read(code_database, USED_STEPS_OF, enrollment_id) == []


def test_a_started_token_and_a_challenge_token_do_not_cross(code_database: CodeDatabase) -> None:
    """Review round 1: the right code of a started (pending) code does not complete a sign-in
    code challenge with the started token, and a `challenge` token is not confirmed as a set-up;
    no session is made."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    starting = new_account(code_database, "l3c-2b.cross-start")
    started = enrollment_token(flow, starting, "l3c-2b-cross")
    secret = begin(flow, started)
    coded = add_account(code_database, "l3c-2b.cross-code")
    assert coded.secret is not None
    challenged = challenge_token(flow, coded, "l3c-2b-cross")
    step = fresh_step(code_database)
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=started, method="totp", code=code_of(secret, step), request_id="c"
        )
    with pytest.raises(AuthenticationRejected):
        flow.confirm_mfa_enrollment(
            preauth_token=challenged, code=code_of(coded.secret, step), request_id="c"
        )
    assert read(code_database, SESSIONS_OF, starting.actor_id) == []
    assert read(code_database, SESSIONS_OF, coded.actor_id) == []


def test_a_code_turned_off_while_the_first_code_waits_is_refused(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (reviewer's set-up): the started code is turned off in a transaction that
    is not yet committed; the right first code waits for its row, then finds it no longer
    pending and is refused; nothing is written and the count is not cleared."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.off-while-waiting")
    preauth = enrollment_token(flow, account, "l3c-2b-off-waiting")
    secret = begin(flow, preauth)
    enrollment_id = read(code_database, CODES_OF, account.actor_id)[0][0]
    step = fresh_step(code_database)
    outcomes: list[str] = []

    def confirm() -> None:
        try:
            flow.confirm_mfa_enrollment(
                preauth_token=preauth, code=code_of(secret, step), request_id="t"
            )
            outcomes.append("authenticated")
        except AuthenticationRejected:
            outcomes.append("rejected")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(TURN_CODE_OFF, (account.actor_id, enrollment_id))
        confirming = threading.Thread(target=confirm)
        confirming.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 1:
            time.sleep(0.05)
        assert lock_waits(code_database) >= 1 and confirming.is_alive()
        holder.commit()
    confirming.join(timeout=15)
    assert outcomes == ["rejected"]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []
    assert read(code_database, USED_STEPS_OF, enrollment_id) == []
    assert [row[2] for row in read(code_database, CHALLENGES_OF, account.actor_id)] == [False]
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(0,)]


@pytest.mark.parametrize("case", ["wait", "password", "sign_in_code", "account"])
def test_a_change_before_the_first_code_refuses_and_rolls_everything_back(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """A change committed after the started challenge was read and its wait checked, before the
    session transaction, is met inside that transaction: a wait that 3 parallel wrong codes
    started (429), the started sign-in code turned off (the lock of the pending code), a new
    password (the verifier comparison) and the account disabled (the live session read back);
    the sign-in code is not activated and nothing else is written."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, f"l3c-2b.window-{case}")
    preauth = enrollment_token(flow, account, f"l3c-2b-window-{case}")
    secret = begin(flow, preauth)
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[0]
    enrollment_id = read(code_database, CODES_OF, account.actor_id)[0][0]
    checked = flow._sign_in_waits.challenge_wait_seconds

    def checked_then_changed(username_digest: bytes, source_digest: bytes) -> int | None:
        waiting = checked(username_digest, source_digest)
        if case == "wait":
            with psycopg.connect(code_database.runtime_url) as connection:
                for _ in range(3):
                    connection.execute(
                        "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')",
                        (bytes(stored[4]), bytes(stored[5])),
                    )
                    connection.commit()
        else:
            statement, parameters = change_for(case, account)
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(statement, parameters)
                connection.commit()
        return waiting

    monkeypatch.setattr(flow._sign_in_waits, "challenge_wait_seconds", checked_then_changed)
    refusal: type[Exception] = (
        AuthenticationRateLimited if case == "wait" else AuthenticationRejected
    )
    with pytest.raises(refusal):
        flow.confirm_mfa_enrollment(
            preauth_token=preauth, code=code_of(secret, fresh_step(code_database)), request_id="x"
        )
    state = "disabled" if case == "sign_in_code" else "pending"
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == [state]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []
    assert read(code_database, PROOFS_OF, account.actor_id) == []
    assert read(code_database, USED_STEPS_OF, enrollment_id) == []
    assert [row[2] for row in read(code_database, CHALLENGES_OF, account.actor_id)] == [False]
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(0,)]


def test_two_parallel_first_codes_make_one_session(code_database: CodeDatabase) -> None:
    """Two confirmations of one started challenge with the same right code at the same moment,
    while the table owner holds the pending code's row: the first waits for the row and the
    second behind it (the wrong-try clear's username lock, review round 2); exactly one
    activates the code and makes a session, the other is refused."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = new_account(code_database, "l3c-2b.parallel")
    preauth = enrollment_token(flow, account, "l3c-2b-parallel")
    secret = begin(flow, preauth)
    enrollment_id = read(code_database, CODES_OF, account.actor_id)[0][0]
    step = fresh_step(code_database)
    outcomes: list[str] = []

    def confirm() -> None:
        try:
            flow.confirm_mfa_enrollment(
                preauth_token=preauth, code=code_of(secret, step), request_id="p"
            )
            outcomes.append("authenticated")
        except AuthenticationRejected:
            outcomes.append("rejected")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.totp_mfa_enrollments WHERE enrollment_id = %s FOR UPDATE",
            (enrollment_id,),
        )
        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 2:
            time.sleep(0.05)
        waited = lock_waits(code_database)
        holder.commit()
    assert waited >= 2
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(outcomes) == ["authenticated", "rejected"]
    assert len(read(code_database, SESSIONS_OF, account.actor_id)) == 1
    assert read(code_database, USED_STEPS_OF, enrollment_id) == [(step,)]


def test_the_assurance_is_none_once_the_sign_in_code_of_the_proof_is_off(
    code_database: CodeDatabase,
) -> None:
    """Review round 3 of L3c-2a: a Staff account with MFA `optional` signed in with its sign-in
    code keeps a live session when the code is turned off (it no longer needs MFA), but the
    session no longer claims `totp`."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    account = add_account(
        code_database, "l3c-2b.optional-off", account_class="staff", mfa="optional"
    )
    preauth = challenge_token(flow, account, "l3c-2b-optional")
    assert account.secret is not None
    done = flow.complete_mfa(
        preauth_token=preauth,
        method="totp",
        code=code_of(account.secret, fresh_step(code_database)),
        request_id="o",
    )
    assert done.session_token is not None
    assert flow.inspect_session(session_token=done.session_token, request_id="o").mfa_assurance == (
        "totp"
    )
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        connection.commit()
    assert flow.inspect_session(session_token=done.session_token, request_id="o").mfa_assurance == (
        "none"
    )
    assert resolver(request_with(f"__Host-prm_session={done.session_token}")) is not None


def test_setting_up_a_sign_in_code_needs_the_protection_key(code_database: CodeDatabase) -> None:
    """Without the protection key, beginning and confirming answer unavailable and write nothing;
    with another key the started code cannot be opened (unavailable, no wrong try counted)."""
    account = new_account(code_database, "l3c-2b.no-key")
    without = PostgresAuthenticationFlow(code_database.runtime_url)
    preauth = enrollment_token(without, account, "l3c-2b-key")
    with pytest.raises(AuthenticationUnavailable):
        without.begin_mfa_enrollment(preauth_token=preauth, request_id="k")
    assert_nothing_started(code_database, account)
    secret = begin(
        PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY), preauth
    )
    code = code_of(secret, fresh_step(code_database))
    for flow in (
        without,
        PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=bytes(32)),
    ):
        with pytest.raises(AuthenticationUnavailable):
            flow.confirm_mfa_enrollment(preauth_token=preauth, code=code, request_id="k")
    assert read(code_database, TRIES_OF, username_key(account.username)) == []
    assert [row[1] for row in read(code_database, CODES_OF, account.actor_id)] == ["pending"]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []


def test_the_set_up_routes_answer_the_link_once_then_401_and_set_the_session_cookie(
    code_database: CodeDatabase,
) -> None:
    """API-096 over HTTP: the password sets the pre-authentication cookie with
    `mfa_enrollment_required`; the enrollment route answers the provisioning link with
    `Cache-Control: no-store`, and 401 the second time; a wrong first code answers 401; the
    right code sets the session cookie and removes the pre-authentication cookie."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    app = create_app(
        Settings(database_url=SecretStr(code_database.runtime_url), allowed_browser_origin=ORIGIN),
        authentication_flow=flow,
    )
    account = new_account(code_database, "l3c-2b.http")
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": account.username, "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": "l3c-2b-http"},
        )
        assert login.status_code == 200
        assert login.json()["data"] == {"phase": "mfa_enrollment_required", "session": None}
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies["__Host-prm_csrf"],
            "X-Request-ID": "l3c-2b-http",
        }
        started = client.post("/api/v1/auth/mfa/enrollment", headers=headers)
        assert started.status_code == 200
        assert started.headers["Cache-Control"] == "no-store"
        assert started.json()["data"]["method"] == "totp"
        assert started.json()["data"]["qr_code_svg"] == provisioning_qr_svg(
            started.json()["data"]["provisioning_uri"]
        )
        link = urlsplit(started.json()["data"]["provisioning_uri"])
        secret = TotpSecret.from_base32(parse_qs(link.query)["secret"][0])
        assert client.post("/api/v1/auth/mfa/enrollment", headers=headers).status_code == 401
        step = fresh_step(code_database)
        wrong = client.post(
            "/api/v1/auth/mfa/enrollment/confirm",
            json={"code": wrong_code_of(secret, step)},
            headers=headers,
        )
        assert wrong.status_code == 401
        done = client.post(
            "/api/v1/auth/mfa/enrollment/confirm",
            json={"code": code_of(secret, step)},
            headers=headers,
        )
        assert done.status_code == 200
        assert done.json()["data"]["phase"] == "authenticated"
        assert done.json()["data"]["session"]["mfa_assurance"] == "totp"
        assert done.headers["Cache-Control"] == "no-store"
        assert "__Host-prm_session" in client.cookies
        assert "__Host-prm_preauth" not in client.cookies


def test_the_enrollment_start_and_its_proof_are_guarded_in_the_database(
    code_database: CodeDatabase,
) -> None:
    """DB-AUTH-003, DB-AUTH-004: a start needs an open `enrollment` challenge of its own account,
    an account that is active, has MFA `required` and no active sign-in code, and a new pending
    sign-in code of that account made since the challenge (not one made before it, another
    account's, or a turned-off or active one); a challenge starts once; a start
    never changes and cannot be deleted or truncated; a `totp` proof of an `enrollment`
    challenge names only the sign-in code it started; the runtime role has only the column
    privileges it needs."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    # A Staff account, so its MFA can be made `optional` below (Owner and Manager accounts
    # always need MFA).
    account = new_account(code_database, "l3c-2b.guards", account_class="staff")
    other = new_account(code_database, "l3c-2b.guards-other")
    with psycopg.connect(code_database.owner_url) as connection:
        early_code = add_pending_code(connection, account.actor_id)
        connection.commit()
    token = enrollment_token(flow, account, "l3c-2b-guards")
    other_token = enrollment_token(flow, other, "l3c-2b-guards")
    coded = add_account(code_database, "l3c-2b.guards-coded")
    challenge = challenge_token(flow, coded, "l3c-2b-guards")
    # A pending code made before the challenge is not started by it.
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="new pending code"):
            connection.execute(ADD_START, (account.actor_id, early_code, digest(token)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
            "disabled_by_actor_id = %s, disablement_provenance = 'l3c-2b-guard-test' "
            "WHERE enrollment_id = %s",
            (account.actor_id, early_code),
        )
        account_code = add_pending_code(connection, account.actor_id)
        other_code = add_pending_code(connection, other.actor_id)
        connection.commit()
    cases = (
        ((coded.actor_id, account_code, digest(challenge)), "open enrollment challenge"),
        ((other.actor_id, account_code, digest(token)), "open enrollment challenge"),
        ((account.actor_id, other_code, digest(token)), "new pending code"),
        ((account.actor_id, early_code, digest(token)), "new pending code"),
        ((account.actor_id, coded.enrollment_id, digest(token)), "new pending code"),
    )
    for parameters, message in cases:
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match=message):
                connection.execute(ADD_START, parameters)
    # Review round 1: a code of the account made since the challenge but turned off is not
    # started (the pending condition alone).
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account_code))
        with pytest.raises(errors.IntegrityConstraintViolation, match="new pending code"):
            connection.execute(ADD_START, (account.actor_id, account_code, digest(token)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET mfa_policy_class = 'optional' WHERE actor_id = %s",
            (account.actor_id,),
        )
        with pytest.raises(errors.IntegrityConstraintViolation, match="open enrollment challenge"):
            connection.execute(ADD_START, (account.actor_id, account_code, digest(token)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (other.actor_id, other_code))
        add_sign_in_code(connection, other.actor_id)
        with pytest.raises(errors.IntegrityConstraintViolation, match="without one"):
            connection.execute(ADD_START, (other.actor_id, other_code, digest(other_token)))
    # A new pending code made since the challenge starts it, once.
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
            "disabled_by_actor_id = %s, disablement_provenance = 'l3c-2b-guard-test' "
            "WHERE enrollment_id = %s",
            (account.actor_id, account_code),
        )
        fresh_code = add_pending_code(connection, account.actor_id)
        connection.execute(ADD_START, (account.actor_id, fresh_code, digest(token)))
        connection.commit()
    # Review round 1: the second start of the challenge, with another new pending code, meets the
    # challenge's primary key.
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, fresh_code))
        another_code = add_pending_code(connection, account.actor_id)
        with pytest.raises(errors.UniqueViolation, match="sign_in_code_enrollment_starts_pkey"):
            connection.execute(ADD_START, (account.actor_id, another_code, digest(token)))
    for statement in (
        "UPDATE app.sign_in_code_enrollment_starts SET started_at = started_at WHERE actor_id = %s",
        "DELETE FROM app.sign_in_code_enrollment_starts WHERE actor_id = %s",
    ):
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
                connection.execute(statement, (account.actor_id,))
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
            connection.execute("TRUNCATE app.sign_in_code_enrollment_starts CASCADE")
    # A `totp` proof of a completed `enrollment` challenge names only the code it started.
    enrolled = new_account(code_database, "l3c-2b.guards-proof")
    proof_token = enrollment_token(flow, enrolled, "l3c-2b-guards")
    secret = begin(flow, proof_token)
    done = flow.confirm_mfa_enrollment(
        preauth_token=proof_token, code=code_of(secret, fresh_step(code_database)), request_id="g"
    )
    assert done.session_token is not None
    with psycopg.connect(code_database.owner_url) as connection:
        session_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
            "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)",
            (session_id, enrolled.actor_id, digest(f"proof-{session_id}"), PROVENANCE),
        )
        with pytest.raises(errors.IntegrityConstraintViolation, match="names the challenge"):
            connection.execute(
                "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
                "enrollment_id) SELECT %s, challenge_id, 'totp', %s "
                "FROM app.sign_in_mfa_challenges WHERE token_verifier = %s",
                (session_id, coded.enrollment_id, digest(proof_token)),
            )
    with psycopg.connect(code_database.owner_url) as connection:
        privileges = connection.execute(
            "SELECT has_column_privilege('prm_runtime', 'app.sign_in_code_enrollment_starts', "
            "'enrollment_id', 'INSERT'), has_column_privilege('prm_runtime', "
            "'app.sign_in_code_enrollment_starts', 'started_at', 'INSERT'), "
            "has_column_privilege('prm_runtime', 'app.sign_in_code_enrollment_starts', "
            "'enrollment_id', 'UPDATE'), has_table_privilege('prm_runtime', "
            "'app.sign_in_code_enrollment_starts', 'DELETE'), has_table_privilege("
            "'prm_runtime', 'app.sign_in_code_enrollment_starts', 'TRUNCATE')"
        ).fetchone()
    assert privileges == (True, False, False, False, False)


def test_a_totp_proof_of_a_set_up_needs_its_own_start_and_a_step_used_since(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (both reviewers; set-ups written as the table owner after a real start):
    each condition of the new proof case alone, with a positive control. A completed `enrollment`
    challenge whose started code is active but has no used step gets no `totp` proof; after a
    step is used, the same proof is accepted. A completed `enrollment` challenge that started
    nothing gets no proof for the code another challenge of the account started, while that
    other challenge, completed, gets it."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    activate = (
        "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'active', "
        "activated_by_actor_id = actor_id, activation_provenance = 'l3c-2b-proof-test' "
        "WHERE enrollment_id = %s"
    )
    complete = (
        "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
        "WHERE token_verifier = %s"
    )
    add_session = (
        "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
        "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)"
    )
    add_proof = (
        "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
        "enrollment_id) SELECT %s, challenge_id, 'totp', %s "
        "FROM app.sign_in_mfa_challenges WHERE token_verifier = %s"
    )
    use_step = "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)"

    # No used step since the challenge.
    first = new_account(code_database, "l3c-2b.proof-no-step")
    token = enrollment_token(flow, first, "l3c-2b-proof")
    begin(flow, token)
    code = read(code_database, CODES_OF, first.actor_id)[0][0]
    session_id = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(activate, (code,))
        connection.execute(complete, (digest(token),))
        connection.execute(
            add_session, (session_id, first.actor_id, digest(f"no-step-{session_id}"), PROVENANCE)
        )
        connection.commit()
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="names the challenge"):
            connection.execute(add_proof, (session_id, code, digest(token)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (code, fresh_step(code_database)))
        connection.execute(add_proof, (session_id, code, digest(token)))
        connection.commit()
    assert read(code_database, PROOFS_OF, first.actor_id) == [("totp", code)]

    # Another challenge of the account, which started nothing.
    second = new_account(code_database, "l3c-2b.proof-other-challenge")
    starter = enrollment_token(flow, second, "l3c-2b-proof")
    bystander = enrollment_token(flow, second, "l3c-2b-proof")
    begin(flow, starter)
    code = read(code_database, CODES_OF, second.actor_id)[0][0]
    session_id = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(activate, (code,))
        connection.execute(use_step, (code, fresh_step(code_database)))
        connection.execute(complete, (digest(bystander),))
        connection.execute(
            add_session, (session_id, second.actor_id, digest(f"other-{session_id}"), PROVENANCE)
        )
        connection.commit()
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="names the challenge"):
            connection.execute(add_proof, (session_id, code, digest(bystander)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(complete, (digest(starter),))
        connection.execute(add_proof, (session_id, code, digest(starter)))
        connection.commit()
    assert read(code_database, PROOFS_OF, second.actor_id) == [("totp", code)]


def test_the_sign_in_code_enrollment_migration_follows_l3c_2a_and_is_forward_only() -> None:
    """The migration chain: `20270131_188` follows `20270130_187` and has no downgrade."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
