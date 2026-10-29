"""Login sub-slice L3b: wrong sign-in tries counted in the database, and the waits they start.

DL-080 item 10 as amended by the owner (DL-081), Q-2026-10-21-154 (a), SEC-012, UI-109,
API-096, DB-AUTH-011 (migration `20270128_185`). One throwaway database at head; accounts and
real Argon2id credentials are written as the table owner; earlier tries and waits are written as
the table owner with times taken back from the database clock, and every sign-in runs as the
runtime role through `PostgresAuthenticationFlow`. Each test uses its own accounts and request
sources, so the order of the tests does not matter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

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
)
from property_rental.auth_flow import (
    PostgresAuthenticationFlow,
    _PostgresSignInWaits,
    sign_in_source_digest,
    sign_in_username_digest,
)
from property_rental.local_authentication import (
    AuthenticationResult,
    normalize_local_username,
)
from property_rental.password_security import PasswordHashService, PasswordVerification
from property_rental.runtime_secrets import derive_sign_in_try_key
from property_rental.settings import Settings
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

REVISION = "20270128_185"
PREVIOUS = "20270127_184"
# The head since V1-060 (migration 20270331_250, Sign Lease refuses an ended Reservation).
HEAD = "20270402_252"
# The migration of login sub-slice L3c-1.
KEYED_CLEAR = "20270129_186"
PASSWORD = "correct horse battery staple"
WRONG = "wrong horse battery staple"
ORIGIN = "https://property.test"
PROVENANCE = "login-slice-l3b-test"
TABLES = ("sign_in_wrong_tries", "sign_in_waits", "sign_in_try_clears")
TIME_COLUMNS = {
    "sign_in_wrong_tries": "tried_at",
    "sign_in_waits": "ends_at",
    "sign_in_try_clears": "cleared_at",
}
FUNCTIONS = (
    "app.sign_in_wait_seconds(bytea,bytea)",
    "app.record_sign_in_wrong_try(bytea,bytea,text)",
    "app.clear_sign_in_wrong_tries(bytea,bytea,uuid)",
)
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    f"lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,%s,%s,%s,%s,'{PROVENANCE}')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    f"VALUES (%s,%s,'{PROVENANCE}')"
)
ADD_CREDENTIAL = (
    "INSERT INTO app.password_credentials(actor_id,verifier_encoding,algorithm,"
    "work_factor_metadata,provenance) VALUES (%s,%s,%s,%s::jsonb,'initial-credential')"
)
# Earlier wrong tries and waits, written as the table owner with times taken back from the
# database clock.
ADD_TRY = (
    "INSERT INTO app.sign_in_wrong_tries (username_digest, source_digest, try_kind, tried_at) "
    "VALUES (%s, %s, 'password', statement_timestamp() - %s::interval) RETURNING try_no"
)
ADD_WAIT = (
    "INSERT INTO app.sign_in_waits (wait_scope, key_digest, starts_at, ends_at, wrong_try_no) "
    "VALUES (%s, %s, statement_timestamp() - %s::interval, "
    "statement_timestamp() + %s::interval, %s)"
)
TRIES_OF = "SELECT count(*) FROM app.sign_in_wrong_tries WHERE username_digest = %s"
WAITS_OF = (
    "SELECT wait_scope, extract(epoch FROM ends_at - starts_at)::integer, ends_at "
    "FROM app.sign_in_waits "
    "WHERE key_digest = %s ORDER BY wait_no"
)
CLEARS_OF = (
    "SELECT actor_id, covers_through_try_no FROM app.sign_in_try_clears "
    "WHERE username_digest = %s ORDER BY clear_no"
)
LAST_TRY_OF = "SELECT max(try_no) FROM app.sign_in_wrong_tries WHERE username_digest = %s"


@dataclass(frozen=True)
class WaitDatabase:
    owner_url: str
    runtime_url: str


@pytest.fixture(scope="module")
def wait_database(migrated_database_url: str) -> Iterator[WaitDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_sign_in_wait") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        yield WaitDatabase(temporary, runtime_url)


def add_account(
    database: WaitDatabase,
    username: str,
    *,
    account_class: str = "staff",
    lifecycle: str = "active",
    mfa: str = "optional",
) -> uuid.UUID:
    """An account with a class and the test password, written as the table owner."""
    credential = PasswordHashService().hash_password(PASSWORD)
    actor_id = uuid.uuid4()
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(ADD_ACCOUNT, (actor_id, username, username, username, lifecycle, mfa))
        connection.execute(ADD_CLASS, (actor_id, account_class))
        connection.execute(
            ADD_CREDENTIAL,
            (
                actor_id,
                credential.verifier_encoding,
                credential.algorithm,
                json.dumps(dict(credential.work_factor_metadata)),
            ),
        )
        connection.commit()
    return actor_id


def username_key(username: str) -> bytes:
    return sign_in_username_digest(normalize_local_username(username))


def add_tries(
    database: WaitDatabase, username: str, source: str, count: int, ago: str
) -> list[int]:
    numbers = []
    with psycopg.connect(database.owner_url) as connection:
        for _ in range(count):
            row = connection.execute(
                ADD_TRY, (username_key(username), sign_in_source_digest(source), ago)
            ).fetchone()
            assert row is not None
            numbers.append(int(str(row[0])))
        connection.commit()
    return numbers


def add_wait(
    database: WaitDatabase, scope: str, key: bytes, started_ago: str, ends_in: str, try_no: int
) -> None:
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(ADD_WAIT, (scope, key, started_ago, ends_in, try_no))
        connection.commit()


def read(database: WaitDatabase, query: str, key: bytes) -> list[tuple[object, ...]]:
    with psycopg.connect(database.owner_url) as connection:
        return connection.execute(query, (key,)).fetchall()


def sign_in(flow: PostgresAuthenticationFlow, username: str, password: str, source: str) -> int:
    """Sign in and answer the seconds of the wait, or 0 for a plain rejection; a sign-in that
    makes a session or needs MFA answers -1."""
    try:
        flow.login(username=username, password=password, request_source=source, request_id="l3b")
    except AuthenticationRateLimited as waiting:
        assert waiting.retry_after_seconds is not None
        return waiting.retry_after_seconds
    except AuthenticationRejected:
        return 0
    return -1


def test_the_owners_example_3_wrong_tries_wait_5_minutes_then_every_2_more_wait_15(
    wait_database: WaitDatabase,
) -> None:
    """The owner's example: Sokha types the wrong password 3 times and waits 5 minutes; the
    right password is refused during the wait, and tries during it add no row and do not move
    its end. After the wait (written as earlier history) the 4th wrong try gives no wait and the
    5th a 15-minute wait; after that the 6th gives none and the 7th 15 minutes again."""
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    add_account(wait_database, "l3b.sokha")
    key = username_key("l3b.sokha")
    assert [sign_in(flow, "l3b.sokha", WRONG, f"l3b-ex-{n}") for n in range(3)] == [0, 0, 300]
    waits = read(wait_database, WAITS_OF, key)
    assert [(row[0], row[1]) for row in waits] == [("username", 300)]
    for password in (PASSWORD, WRONG):
        seconds = sign_in(flow, "L3B.Sokha ", password, "l3b-ex-other")
        assert 0 < seconds <= 300
    assert read(wait_database, TRIES_OF, key) == [(3,)]
    assert read(wait_database, WAITS_OF, key) == waits

    # The 5-minute wait of the 3rd try is over: the 4th wrong try gives no wait, the 5th 15.
    add_account(wait_database, "l3b.after5")
    after5 = username_key("l3b.after5")
    tries = add_tries(wait_database, "l3b.after5", "l3b-ex-old", 3, "6 minutes")
    add_wait(wait_database, "username", after5, "6 minutes", "-1 minute", tries[-1])
    assert [sign_in(flow, "l3b.after5", WRONG, "l3b-ex-5") for _ in range(2)] == [0, 900]
    assert [row[:2] for row in read(wait_database, WAITS_OF, after5)] == [
        ("username", 300),
        ("username", 900),
    ]

    # The 15-minute wait of the 5th try is over: the 6th gives no wait, the 7th 15 again.
    add_account(wait_database, "l3b.after15")
    after15 = username_key("l3b.after15")
    tries = add_tries(wait_database, "l3b.after15", "l3b-ex-old", 5, "30 minutes")
    add_wait(wait_database, "username", after15, "30 minutes", "-25 minutes", tries[2])
    add_wait(wait_database, "username", after15, "20 minutes", "-5 minutes", tries[4])
    assert [sign_in(flow, "l3b.after15", WRONG, "l3b-ex-7") for _ in range(2)] == [0, 900]
    assert read(wait_database, TRIES_OF, after15) == [(7,)]


def test_a_correct_sign_in_just_after_the_wait_clears_the_count(
    wait_database: WaitDatabase,
) -> None:
    """Just before the end of the wait the right password is refused; just after it a session
    is made and the count is cleared, so 3 more wrong tries start the 5-minute wait again (not a
    15-minute one); a correct sign-in with no wrong try records no clear."""
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    add_account(wait_database, "l3b.edge")
    key = username_key("l3b.edge")
    tries = add_tries(wait_database, "l3b.edge", "l3b-edge-old", 3, "5 minutes")
    add_wait(wait_database, "username", key, "4 minutes 30 seconds", "30 seconds", tries[-1])
    assert 0 < sign_in(flow, "l3b.edge", PASSWORD, "l3b-edge") <= 30

    add_account(wait_database, "l3b.ended")
    ended = username_key("l3b.ended")
    tries = add_tries(wait_database, "l3b.ended", "l3b-edge-old", 3, "5 minutes")
    add_wait(wait_database, "username", ended, "5 minutes 1 second", "-1 second", tries[-1])
    assert sign_in(flow, "l3b.ended", PASSWORD, "l3b-edge") == -1
    clears = read(wait_database, CLEARS_OF, ended)
    assert [row[1] for row in clears] == [tries[-1]]
    assert [sign_in(flow, "l3b.ended", WRONG, "l3b-edge-again") for _ in range(3)] == [0, 0, 300]

    # Review round 2: the database digest of a username that is not ASCII matches the Python
    # one, so a correct sign-in clears its count.
    add_account(wait_database, "l3b.zo\u00eb")
    zoe = username_key("l3b.zo\u00eb")
    zoe_tries = add_tries(wait_database, "l3b.zo\u00eb", "l3b-edge-old", 2, "1 minute")
    assert sign_in(flow, "L3B.ZO\u00cb ", PASSWORD, "l3b-edge") == -1
    assert [row[1] for row in read(wait_database, CLEARS_OF, zoe)] == [zoe_tries[-1]]

    add_account(wait_database, "l3b.clean")
    assert sign_in(flow, "l3b.clean", PASSWORD, "l3b-edge") == -1
    assert read(wait_database, CLEARS_OF, username_key("l3b.clean")) == []


def test_the_wait_answer_is_the_same_for_a_known_and_an_unknown_username(
    wait_database: WaitDatabase,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Through `create_app`: 3 wrong tries for an existing and for an unknown username give the
    same 401 answers and then the same 429 answer (`RATE_LIMITED`, `Retry-After: 300`,
    `no-store`); the next try, even with the right password, gets 429 too; no username,
    password or source text reaches the rows or the log."""
    caplog.set_level(logging.DEBUG)
    add_account(wait_database, "l3b.http")
    app = create_app(
        Settings(database_url=SecretStr(wait_database.runtime_url), allowed_browser_origin=ORIGIN)
    )
    answers: dict[str, list[tuple[int, object, str | None, str | None]]] = {}
    with TestClient(app, base_url="https://testserver") as client:
        for username in ("l3b.http", "l3b.nobody"):
            answers[username] = []
            for password in (WRONG, WRONG, WRONG, PASSWORD):
                answer = client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": password},
                    headers={"Origin": ORIGIN, "X-Request-ID": "l3b-http"},
                )
                answers[username].append(
                    (
                        answer.status_code,
                        answer.json(),
                        answer.headers.get("Retry-After"),
                        answer.headers.get("Cache-Control"),
                    )
                )
                assert "set-cookie" not in answer.headers
    assert answers["l3b.http"][:3] == answers["l3b.nobody"][:3]
    assert [entry[0] for entry in answers["l3b.http"]] == [401, 401, 429, 429]
    third = answers["l3b.http"][2]
    assert third[1] == {
        "error": {
            "code": "RATE_LIMITED",
            "message": "Too many requests.",
            "fields": [],
            "rule_ids": [],
            "current_version": None,
        },
        "meta": {"request_id": "l3b-http"},
    }
    assert (third[2], third[3]) == ("300", "no-store")
    for entry in (answers["l3b.http"][3], answers["l3b.nobody"][3]):
        assert entry[0] == 429 and entry[1] == third[1] and entry[3] == "no-store"
        assert entry[2] is not None and 0 < int(entry[2]) <= 300

    with psycopg.connect(wait_database.owner_url) as connection:
        stored = b"".join(
            bytes(value)
            for table in TABLES
            for row in connection.execute(f"SELECT * FROM app.{table}").fetchall()
            for value in row
            if isinstance(value, bytes | memoryview)
        )
    for text in ("l3b.http", "l3b.nobody", WRONG, PASSWORD, "testclient"):
        assert text.encode() not in stored
        assert text not in caplog.text


def test_a_disabled_account_counts_and_an_mfa_password_neither_counts_nor_clears(
    wait_database: WaitDatabase,
) -> None:
    """The right password of a disabled account is a wrong try (the same answers as for any
    other username). The right password of an account that needs MFA gives the MFA step and
    neither adds to nor clears the count, so one more wrong try is the 3rd and starts the
    5-minute wait."""
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    add_account(wait_database, "l3b.disabled", lifecycle="disabled")
    assert [sign_in(flow, "l3b.disabled", PASSWORD, "l3b-dis") for _ in range(3)] == [0, 0, 300]

    add_account(wait_database, "l3b.manager", account_class="manager", mfa="required")
    key = username_key("l3b.manager")
    add_tries(wait_database, "l3b.manager", "l3b-mfa-old", 2, "1 minute")
    result = flow.login(
        username="l3b.manager", password=PASSWORD, request_source="l3b-mfa", request_id="l3b"
    )
    # Login sub-slice L3c-2a: an account without a sign-in code is asked to set one up.
    assert result.phase is AuthenticationPhase.MFA_ENROLLMENT_REQUIRED and result.session is None
    assert read(wait_database, TRIES_OF, key) == [(2,)]
    assert read(wait_database, CLEARS_OF, key) == []
    assert sign_in(flow, "l3b.manager", WRONG, "l3b-mfa") == 300


def test_a_source_waits_15_minutes_after_20_wrong_tries_in_15_minutes(
    wait_database: WaitDatabase,
) -> None:
    """20 wrong tries from one source in 15 minutes, for different usernames, start a 15-minute
    wait for that source: every try from it is refused, also a right password, while the same
    account signs in from another source. Tries older than 15 minutes do not count, and a source
    whose wait has ended signs in again."""
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    for n in range(19):
        add_tries(wait_database, f"l3b.spray-{n}", "l3b-spray", 1, "14 minutes")
    assert sign_in(flow, "l3b.spray-last", WRONG, "l3b-spray") == 900
    source = sign_in_source_digest("l3b-spray")
    assert [row[0] for row in read(wait_database, WAITS_OF, source)] == ["source"]
    add_account(wait_database, "l3b.desk")
    assert 0 < sign_in(flow, "l3b.desk", PASSWORD, "l3b-spray") <= 900
    assert sign_in(flow, "l3b.desk", PASSWORD, "l3b-other") == -1

    for n in range(19):
        add_tries(wait_database, f"l3b.old-{n}", "l3b-old-source", 1, "16 minutes")
    assert sign_in(flow, "l3b.old-last", WRONG, "l3b-old-source") == 0

    tries = add_tries(wait_database, "l3b.ended-source", "l3b-ended-source", 1, "16 minutes")
    ended = sign_in_source_digest("l3b-ended-source")
    add_wait(wait_database, "source", ended, "16 minutes", "-1 minute", tries[0])
    assert sign_in(flow, "l3b.desk", PASSWORD, "l3b-ended-source") == -1


def test_the_clear_and_the_count_add_nothing_while_a_wait_is_active(
    wait_database: WaitDatabase,
) -> None:
    """Run as the runtime role: during an active wait the clear answers the wait and records no
    clear (a wait started by a parallel try wins over a sign-in checked before it), and the
    count answers the wait and records no try; a clear for a disabled account records nothing;
    the wait read answers NULL without a wait."""
    actor_id = add_account(wait_database, "l3b.race")
    key = username_key("l3b.race")
    source = sign_in_source_digest("l3b-race")
    tries = add_tries(wait_database, "l3b.race", "l3b-race", 3, "1 minute")
    add_wait(wait_database, "username", key, "1 minute", "4 minutes", tries[-1])
    disabled = add_account(wait_database, "l3b.race-off", lifecycle="disabled")
    off_key = username_key("l3b.race-off")
    add_tries(wait_database, "l3b.race-off", "l3b-race", 1, "1 minute")
    with psycopg.connect(wait_database.runtime_url) as connection:
        cleared = connection.execute(
            "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)", (key, source, actor_id)
        ).fetchone()
        counted = connection.execute(
            "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')", (key, source)
        ).fetchone()
        waiting = connection.execute(
            "SELECT app.sign_in_wait_seconds(%s, %s)", (key, source)
        ).fetchone()
        free = connection.execute(
            "SELECT app.sign_in_wait_seconds(%s, %s)",
            (username_key("l3b.free"), sign_in_source_digest("l3b-free")),
        ).fetchone()
        off = connection.execute(
            "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)", (off_key, source, disabled)
        ).fetchone()
        connection.commit()
    for answer in (cleared, counted, waiting):
        assert answer is not None and 180 < int(str(answer[0])) <= 240
    assert free == (None,) and off == (None,)
    assert read(wait_database, CLEARS_OF, key) == []
    assert read(wait_database, TRIES_OF, key) == [(3,)]
    assert read(wait_database, CLEARS_OF, off_key) == []


def test_the_try_relations_are_append_only_and_only_the_functions_are_open_to_the_runtime(
    wait_database: WaitDatabase,
) -> None:
    """The three relations refuse UPDATE, DELETE and TRUNCATE, also from their owner; the runtime
    role has no privilege on them and EXECUTE only on the three definer functions (pinned
    `search_path`, no PUBLIC EXECUTE); the functions refuse a transaction that is not READ
    COMMITTED, a key that is not a sha256 digest and an unknown try kind; the migration follows
    `20270127_184` and refuses a downgrade (the head is `20270331_250` since V1-060 followed V1-058,
    the Waiting for approval read)."""
    tries = add_tries(wait_database, "l3b.guard", "l3b-guard", 1, "1 minute")
    key = username_key("l3b.guard")
    source = sign_in_source_digest("l3b-guard")
    actor_id = add_account(wait_database, "l3b.guard")
    add_wait(wait_database, "username", key, "5 minutes 30 seconds", "-30 seconds", tries[0])
    with psycopg.connect(wait_database.runtime_url) as connection:
        assert connection.execute(
            "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)", (key, source, actor_id)
        ).fetchone() == (None,)
        connection.commit()
    for table in TABLES:
        for statement in (
            f"UPDATE app.{table} SET {TIME_COLUMNS[table]} = statement_timestamp()",
            f"DELETE FROM app.{table}",
            # CASCADE, so the foreign keys between the three do not refuse it first.
            f"TRUNCATE app.{table} CASCADE",
        ):
            with psycopg.connect(wait_database.owner_url) as connection:
                with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
                    connection.execute(statement)
        with psycopg.connect(wait_database.runtime_url) as connection:
            with pytest.raises(errors.InsufficientPrivilege):
                connection.execute(f"SELECT 1 FROM app.{table}")
        with psycopg.connect(wait_database.owner_url) as connection:
            assert connection.execute(
                "SELECT has_table_privilege('prm_runtime', %s, "
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                (f"app.{table}",),
            ).fetchone() == (False,)
    with psycopg.connect(wait_database.owner_url) as connection:
        for function in FUNCTIONS:
            row = connection.execute(
                "SELECT prosecdef, proconfig, has_function_privilege('prm_runtime', %s, 'EXECUTE'),"
                " has_function_privilege('public', %s, 'EXECUTE') FROM pg_proc "
                "WHERE oid = %s::regprocedure",
                (function, function, function),
            ).fetchone()
            assert row == (True, ["search_path=pg_catalog"], True, False)
        assert connection.execute(
            "SELECT has_function_privilege('prm_runtime', "
            "'app.reject_sign_in_try_history_change()', 'EXECUTE')"
        ).fetchone() == (False,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
    calls = (
        ("SELECT app.sign_in_wait_seconds(%s, %s)", (key, source)),
        ("SELECT app.record_sign_in_wrong_try(%s, %s, 'password')", (key, source)),
        ("SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)", (key, source, actor_id)),
    )
    for query, parameters in calls:
        with psycopg.connect(wait_database.runtime_url) as connection:
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            with pytest.raises(errors.ObjectNotInPrerequisiteState):
                connection.execute(query, parameters)
        with psycopg.connect(wait_database.runtime_url) as connection:
            short = (b"short", *parameters[1:])
            with pytest.raises(errors.InvalidParameterValue, match="sha256"):
                connection.execute(query, short)
    with psycopg.connect(wait_database.runtime_url) as connection:
        with pytest.raises(errors.InvalidParameterValue, match="try kind"):
            connection.execute(
                "SELECT app.record_sign_in_wrong_try(%s, %s, 'guess')", (key, source)
            )
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == [HEAD]
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_mfa_step_is_refused_when_a_parallel_wrong_try_started_a_wait(
    wait_database: WaitDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (security, reviewer's set-up): the right password of an account that needs
    MFA is checked again for a wait, under the locks of the count, before the MFA step; a wait
    that a parallel 3rd wrong try started after the first check refuses it with the same wait
    answer and no MFA step."""
    add_account(wait_database, "l3b.mfa-race", account_class="manager", mfa="required")
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    checked = flow._authentication.authenticate

    def checked_then_parallel_wait(
        *, username: str, password: str, request_source: str
    ) -> AuthenticationResult:
        result = checked(username=username, password=password, request_source=request_source)
        tries = add_tries(wait_database, "l3b.mfa-race", "l3b-mfa-race-other", 3, "0 seconds")
        add_wait(
            wait_database,
            "username",
            username_key("l3b.mfa-race"),
            "0 seconds",
            "5 minutes",
            tries[-1],
        )
        return result

    monkeypatch.setattr(flow._authentication, "authenticate", checked_then_parallel_wait)
    assert 0 < sign_in(flow, "l3b.mfa-race", PASSWORD, "l3b-mfa-race") <= 300


def test_a_correct_sign_in_is_refused_when_the_clear_meets_a_parallel_wait(
    wait_database: WaitDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (reviewer's set-up): when the first check saw no wait but a parallel wrong
    try started one, the clear in the session transaction answers the wait: the sign-in gets the
    wait answer, no session is written and nothing is cleared. Review round 3 (Q-2026-10-23-177
    (a)): the password is checked exactly once on that path."""
    actor_id = add_account(wait_database, "l3b.race-flow")
    key = username_key("l3b.race-flow")
    tries = add_tries(wait_database, "l3b.race-flow", "l3b-race-flow", 3, "1 minute")
    add_wait(wait_database, "username", key, "1 minute", "4 minutes", tries[-1])
    monkeypatch.setattr(_PostgresSignInWaits, "wait_seconds", lambda *_: None)
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    # Owner answer (a) to Q-2026-10-23-177: the password is checked exactly once, so the wait
    # answer comes as fast as for a wrong password.
    checks: list[str] = []
    verify = PasswordHashService.verify_password

    def counted(
        service: PasswordHashService, password: str, verifier_encoding: str
    ) -> PasswordVerification:
        checks.append(verifier_encoding)
        return verify(service, password, verifier_encoding)

    monkeypatch.setattr(PasswordHashService, "verify_password", counted)
    assert 180 < sign_in(flow, "l3b.race-flow", PASSWORD, "l3b-race-flow") <= 240
    assert len(checks) == 1
    with psycopg.connect(wait_database.owner_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.browser_sessions WHERE actor_id = %s", (actor_id,)
        ).fetchone() == (0,)
    assert read(wait_database, CLEARS_OF, key) == []


def test_a_clear_needs_an_active_account_but_cannot_check_a_keyed_digest(
    wait_database: WaitDatabase,
) -> None:
    """Review round 1 of L3b; changed with the owner answer (a) to Q-2026-10-23-175 (login
    sub-slice L3c-1, renamed from `test_a_clear_with_another_accounts_actor_clears_nothing`): the
    clear refuses a disabled account's actor, but the database can no longer check that the
    digest is the actor's own username, because the application keys the digest; another active
    account's actor now clears. The flow passes only the signed-in account's own digest."""
    add_account(wait_database, "l3b.owner-of-count")
    other = add_account(wait_database, "l3b.someone-else")
    disabled = add_account(wait_database, "l3b.someone-off", lifecycle="disabled")
    key = username_key("l3b.owner-of-count")
    tries = add_tries(wait_database, "l3b.owner-of-count", "l3b-mismatch", 2, "1 minute")
    answers = []
    for actor in (disabled, other):
        with psycopg.connect(wait_database.runtime_url) as connection:
            answers.append(
                connection.execute(
                    "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)",
                    (key, sign_in_source_digest("l3b-mismatch"), actor),
                ).fetchone()
            )
            connection.commit()
        if actor == disabled:
            assert read(wait_database, CLEARS_OF, key) == []
    assert answers == [(None,), (None,)]
    assert read(wait_database, CLEARS_OF, key) == [(other, tries[-1])]


def test_a_flow_with_the_protected_key_keeps_keyed_digests_and_clears_them(
    wait_database: WaitDatabase,
) -> None:
    """Login sub-slice L3c-1 (owner answer (a) to Q-2026-10-23-175): with the key derived from
    the protected key file, the rows hold HMAC-SHA256 digests, never the plain sha256 ones; the
    3rd wrong try starts the 5-minute wait, and after it ends a correct sign-in clears the keyed
    count (migration 20270129_186 no longer compares the digest)."""
    key = derive_sign_in_try_key(bytes(range(32)))
    flow = PostgresAuthenticationFlow(wait_database.runtime_url, sign_in_try_key=key)
    add_account(wait_database, "l3c1.keyed")
    keyed = sign_in_username_digest("l3c1.keyed", key)
    plain = username_key("l3c1.keyed")
    assert keyed != plain
    assert keyed == hmac.new(key, b"username:l3c1.keyed", hashlib.sha256).digest()
    assert [sign_in(flow, "l3c1.keyed", WRONG, "l3c1-keyed") for _ in range(3)] == [0, 0, 300]
    assert read(wait_database, TRIES_OF, keyed) == [(3,)]
    assert read(wait_database, TRIES_OF, plain) == [(0,)]
    with psycopg.connect(wait_database.owner_url) as connection:
        sources = connection.execute(
            "SELECT DISTINCT source_digest FROM app.sign_in_wrong_tries WHERE username_digest = %s",
            (keyed,),
        ).fetchall()
    assert sources == [(sign_in_source_digest("l3c1-keyed", key),)]

    # After an ended wait (written as earlier history), a correct sign-in clears the keyed count.
    ended_actor = add_account(wait_database, "l3c1.ended")
    ended = sign_in_username_digest("l3c1.ended", key)
    with psycopg.connect(wait_database.owner_url) as connection:
        numbers = []
        for _ in range(3):
            row = connection.execute(
                ADD_TRY, (ended, sign_in_source_digest("l3c1-old", key), "6 minutes")
            ).fetchone()
            assert row is not None
            numbers.append(int(str(row[0])))
        connection.execute(ADD_WAIT, ("username", ended, "6 minutes", "-1 minute", numbers[-1]))
        connection.commit()
    # Review round 1: a correct sign-in clears only its own keyed count, not another account's.
    add_account(wait_database, "l3c1.bystander")
    bystander = sign_in_username_digest("l3c1.bystander", key)
    with psycopg.connect(wait_database.owner_url) as connection:
        for _ in range(2):
            connection.execute(
                ADD_TRY, (bystander, sign_in_source_digest("l3c1-keyed-other", key), "1 minute")
            )
        connection.commit()
    assert sign_in(flow, "l3c1.ended", PASSWORD, "l3c1-keyed-other") == -1
    assert read(wait_database, CLEARS_OF, ended) == [(ended_actor, numbers[-1])]
    assert read(wait_database, CLEARS_OF, bystander) == []
    assert read(wait_database, TRIES_OF, bystander) == [(2,)]

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(KEYED_CLEAR)
    assert revision is not None and revision.down_revision == REVISION
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


LOCKED_CALLS = {
    "record": "SELECT app.record_sign_in_wrong_try(%s, %s, 'password')",
    "read": "SELECT app.sign_in_wait_seconds(%s, %s)",
    "clear": "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)",
}


@pytest.mark.parametrize("function", ["record", "read", "clear"])
def test_each_function_waits_for_the_username_lock_and_then_meets_the_parallel_wait(
    wait_database: WaitDatabase,
    function: str,
) -> None:
    """Review rounds 1 and 2: while another transaction holds the username lock and records the
    3rd wrong try with its wait, the count, the wait read and the clear each wait for the lock
    and then answer that wait: the count records no row and the clear clears nothing (the active
    wait is read after the locks)."""
    username = f"l3b.lock-{function}"
    key = username_key(username)
    source = sign_in_source_digest("l3b-lock")
    earlier = 0
    parameters: tuple[object, ...] = (key, source)
    if function == "clear":
        parameters = (key, source, add_account(wait_database, username))
        earlier = len(add_tries(wait_database, username, "l3b-lock-old", 2, "1 minute"))
    answers: list[tuple[object, ...] | None] = []

    def parallel_call() -> None:
        with psycopg.connect(wait_database.runtime_url) as connection:
            answers.append(connection.execute(LOCKED_CALLS[function], parameters).fetchone())
            connection.commit()

    with psycopg.connect(wait_database.owner_url) as holder:
        holder.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended("
            "'sign-in-username:' || encode(%s::bytea, 'hex'), 0))",
            (key,),
        )
        worker = threading.Thread(target=parallel_call)
        worker.start()
        for _ in range(200):
            waiting = holder.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ).fetchone()
            if waiting is not None and int(str(waiting[0])) > 0:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the parallel call never waited for the username lock")
        numbers = []
        for _ in range(3 - earlier):
            row = holder.execute(ADD_TRY, (key, source, "0 seconds")).fetchone()
            assert row is not None
            numbers.append(int(str(row[0])))
        holder.execute(ADD_WAIT, ("username", key, "0 seconds", "5 minutes", numbers[-1]))
        holder.commit()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert len(answers) == 1 and answers[0] is not None
    assert 0 < int(str(answers[0][0])) <= 300
    assert read(wait_database, TRIES_OF, key) == [(3,)]
    assert [row[:2] for row in read(wait_database, WAITS_OF, key)] == [("username", 300)]
    assert read(wait_database, CLEARS_OF, key) == []


def test_a_wait_has_only_the_lengths_of_the_owners_rule(wait_database: WaitDatabase) -> None:
    """Review round 1: a username wait is 5 or 15 minutes and a source wait 15 minutes; any
    other length is refused by the database."""
    key = username_key("l3b.lengths")
    tries = add_tries(wait_database, "l3b.lengths", "l3b-lengths", 1, "0 seconds")
    for scope, length in (("username", "10 minutes"), ("source", "5 minutes")):
        with psycopg.connect(wait_database.owner_url) as connection:
            with pytest.raises(errors.CheckViolation):
                connection.execute(ADD_WAIT, (scope, key, "0 seconds", length, tries[0]))


def test_a_reset_to_the_same_password_during_sign_in_is_refused(
    wait_database: WaitDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 4 (Q-2026-10-23-177 (a)): the session transaction compares the verifier the
    password was checked against with the stored one, so a reset to the same password after the
    check (a new salted verifier) is refused too, and no session is written."""
    actor_id = add_account(wait_database, "l3b.same-reset")
    flow = PostgresAuthenticationFlow(wait_database.runtime_url)
    replacement = PasswordHashService().hash_password(PASSWORD)
    checked = flow._authentication.authenticate

    def checked_then_reset(
        *, username: str, password: str, request_source: str
    ) -> AuthenticationResult:
        result = checked(username=username, password=password, request_source=request_source)
        with psycopg.connect(wait_database.owner_url) as connection:
            connection.execute(
                "UPDATE app.password_credentials SET verifier_encoding = %s, "
                "changed_by_actor_id = %s, provenance = 'l3b-same-reset-test' WHERE actor_id = %s",
                (replacement.verifier_encoding, actor_id, actor_id),
            )
            connection.commit()
        return result

    monkeypatch.setattr(flow._authentication, "authenticate", checked_then_reset)
    assert sign_in(flow, "l3b.same-reset", PASSWORD, "l3b-same-reset") == 0
    with psycopg.connect(wait_database.owner_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.browser_sessions WHERE actor_id = %s", (actor_id,)
        ).fetchone() == (0,)
