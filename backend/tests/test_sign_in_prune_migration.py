"""V1-056 slice 12c: the Owner removes wrong sign-in tries older than 30 days (DL-092).

Owner answer (a) to Q-2026-10-23-175 (migration `20270217_205`). One throwaway database at head
(the fixture of the L3b tests); rows are written as the table owner with times taken back from
the database clock.
"""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest
from psycopg import errors

from property_rental import sign_in_prune
from test_sign_in_wait_migration import (
    TRIES_OF,
    WaitDatabase,
    add_account,
    read,
    username_key,
    wait_database,
)
from test_sign_in_wait_migration import migrated_database_url as migrated_database_url

__all__ = ["migrated_database_url", "wait_database"]

PRUNE = "app.prune_sign_in_wrong_tries(bytea,integer)"
SOURCE = bytes(32)
ADD_TRY = (
    "INSERT INTO app.sign_in_wrong_tries (username_digest, source_digest, try_kind, tried_at) "
    "VALUES (%s, %s, 'password', statement_timestamp() - %s::interval) RETURNING try_no"
)
ADD_OLD_WAIT = (
    "INSERT INTO app.sign_in_waits (wait_scope, key_digest, starts_at, ends_at, wrong_try_no) "
    "VALUES ('username', %s, statement_timestamp() - %s::interval, "
    "statement_timestamp() - %s::interval + interval '5 minutes', %s)"
)
# A source wait started by a try `%s` ago, 15 minutes long.
ADD_SOURCE_WAIT = (
    "INSERT INTO app.sign_in_waits (wait_scope, key_digest, starts_at, ends_at, wrong_try_no) "
    "VALUES ('source', %s, statement_timestamp() - %s::interval, "
    "statement_timestamp() - %s::interval + interval '15 minutes', %s)"
)
# The count of the owner's rule: the tries after the username's latest clear.
COUNT = (
    "SELECT count(*) FROM app.sign_in_wrong_tries AS wrong WHERE wrong.username_digest = %s "
    "AND wrong.try_no > (SELECT COALESCE(max(clear.covers_through_try_no), 0) "
    "FROM app.sign_in_try_clears AS clear WHERE clear.username_digest = %s)"
)
ADD_CLEAR = (
    "INSERT INTO app.sign_in_try_clears (username_digest, actor_id, covers_through_try_no, "
    "cleared_at) VALUES (%s, %s, %s, statement_timestamp() - %s::interval)"
)


def add_try(database: WaitDatabase, key: bytes, ago: str) -> int:
    with psycopg.connect(database.owner_url) as connection:
        row = connection.execute(ADD_TRY, (key, SOURCE, ago)).fetchone()
    assert row is not None
    return int(str(row[0]))


def owner(database: WaitDatabase, query: str, *parameters: object) -> None:
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(query, parameters)


def count(database: WaitDatabase, key: bytes) -> int:
    with psycopg.connect(database.owner_url) as connection:
        row = connection.execute(COUNT, (key, key)).fetchone()
    assert row is not None
    return int(str(row[0]))


def test_the_prune_removes_only_rows_older_than_30_days(
    wait_database: WaitDatabase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = wait_database
    # Three old tries with an old wait, then a try yesterday: the old ones go.
    old = username_key("prune-old")
    old_tries = [add_try(database, old, "40 days") for _ in range(3)]
    owner(database, ADD_OLD_WAIT, old, "40 days", "40 days", old_tries[-1])
    yesterday = add_try(database, old, "1 day")
    # The only try of a username goes too (a password typed into the username box).
    lonely = username_key("prune-lonely")
    add_try(database, lonely, "40 days")
    # An old clear that a newer clear follows goes with the try it covered; the newer clear
    # keeps its old try.
    cleared = username_key("prune-cleared")
    actor = add_account(database, "prune-cleared")
    first = add_try(database, cleared, "50 days")
    owner(database, ADD_CLEAR, cleared, actor, first, "45 days")
    second = add_try(database, cleared, "40 days")
    owner(database, ADD_CLEAR, cleared, actor, second, "1 day")
    # A username's only clear goes with its old try, and the count stays 0 (review round 1).
    reset = username_key("prune-reset")
    reset_actor = add_account(database, "prune-reset")
    owner(database, ADD_CLEAR, reset, reset_actor, add_try(database, reset, "40 days"), "39 days")
    reset_recent = add_try(database, reset, "1 day")
    # A latest clear that covers a try a remaining wait names stays, so the count stays 0.
    edge = username_key("prune-edge")
    edge_actor = add_account(database, "prune-edge")
    edge_try = add_try(database, edge, "30 days 10 minutes")
    owner(database, ADD_SOURCE_WAIT, SOURCE, "30 days 10 minutes", "30 days 10 minutes", edge_try)
    owner(database, ADD_CLEAR, edge, edge_actor, edge_try, "30 days 5 minutes")
    before = {key: count(database, key) for key in (old, cleared, reset, edge)}
    assert before == {old: 4, cleared: 0, reset: 1, edge: 0}

    # One username per batch: the command goes on until no username is left.
    assert sign_in_prune.prune(database.owner_url, batch=1) == {
        "wrong_tries": 6,
        "waits": 1,
        "clears": 2,
    }
    remaining = "SELECT try_no FROM app.sign_in_wrong_tries WHERE username_digest = %s"
    assert read(database, remaining, old) == [(yesterday,)]
    assert read(database, remaining, lonely) == []
    assert read(database, remaining, cleared) == [(second,)]
    assert read(database, remaining, reset) == [(reset_recent,)]
    assert read(database, remaining, edge) == [(edge_try,)]
    assert read(database, "SELECT count(*) FROM app.sign_in_waits WHERE key_digest = %s", old) == [
        (0,)
    ]
    assert read(
        database,
        "SELECT covers_through_try_no FROM app.sign_in_try_clears WHERE username_digest = %s",
        cleared,
    ) == [(second,)]
    # Old uncleared tries no longer count; a cleared count never grows.
    assert {key: count(database, key) for key in (old, cleared, reset, edge)} == {
        old: 1,
        cleared: 0,
        reset: 1,
        edge: 0,
    }
    # Nothing older is left, so the command removes nothing and prints only the counts.
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database.owner_url)
    assert sign_in_prune.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "event": "sign_in_prune.completed",
        "wrong_tries": 0,
        "waits": 0,
        "clears": 0,
    }


def test_rows_are_removed_only_by_the_prune_and_only_when_old(wait_database: WaitDatabase) -> None:
    database = wait_database
    key = username_key(f"prune-guard-{uuid.uuid4().hex[:8]}")
    old_try = add_try(database, key, "40 days")
    new_try = add_try(database, key, "1 day")
    with psycopg.connect(database.owner_url) as connection:
        # Without the prune's flag even the table owner cannot delete an old row.
        with pytest.raises(errors.IntegrityConstraintViolation):
            connection.execute("DELETE FROM app.sign_in_wrong_tries WHERE try_no = %s", (old_try,))
        connection.rollback()
        connection.execute("SELECT set_config('prm.sign_in_prune', 'on', true)")
        # With it, a row of the last 30 days is still refused, and so is every change.
        with pytest.raises(errors.IntegrityConstraintViolation):
            connection.execute("DELETE FROM app.sign_in_wrong_tries WHERE try_no = %s", (new_try,))
        connection.rollback()
        connection.execute("SELECT set_config('prm.sign_in_prune', 'on', true)")
        with pytest.raises(errors.IntegrityConstraintViolation):
            connection.execute(
                "UPDATE app.sign_in_wrong_tries SET try_kind = 'sign_in_code' WHERE try_no = %s",
                (old_try,),
            )
        connection.rollback()
        with pytest.raises(errors.IntegrityConstraintViolation):
            connection.execute("TRUNCATE app.sign_in_wrong_tries CASCADE")
        connection.rollback()
        assert connection.execute(
            "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE'),"
            "has_function_privilege('prm_financial', %s, 'EXECUTE'),"
            "has_function_privilege('prm_bootstrap', %s, 'EXECUTE'),"
            "has_function_privilege('public', %s, 'EXECUTE')",
            (PRUNE, PRUNE, PRUNE, PRUNE),
        ).fetchone() == (False, False, False, False)
    # The runtime role has no privilege on the relation, flag or not.
    with psycopg.connect(database.runtime_url) as runtime:
        runtime.execute("SELECT set_config('prm.sign_in_prune', 'on', true)")
        with pytest.raises(errors.InsufficientPrivilege):
            runtime.execute("DELETE FROM app.sign_in_wrong_tries WHERE try_no = %s", (old_try,))
        runtime.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            runtime.execute("SELECT * FROM app.prune_sign_in_wrong_tries(NULL, 10)")
    assert read(database, TRIES_OF, key) == [(2,)]
    with psycopg.connect(database.owner_url) as connection:
        for after, limit in ((None, 0), (None, 1001), (b"short", 10)):
            with pytest.raises(errors.InvalidParameterValue):
                connection.execute(
                    "SELECT * FROM app.prune_sign_in_wrong_tries(%s, %s)", (after, limit)
                )
            connection.rollback()


def test_the_prune_command_takes_no_arguments_and_needs_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sign_in_prune.main(["--now"]) == 2
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    assert sign_in_prune.main([]) == 2
    output = capsys.readouterr().out
    assert "sign_in_prune.usage" in output and "sign_in_prune.config_invalid" in output
