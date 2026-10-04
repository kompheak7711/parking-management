"""Source-backed disposition admission, exact replay and forward preservation."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deposit_disposition_test_support import disposition_context
from lease_deposit_forfeiture_test_support import (
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from property_rental.deposit import (
    DepositAuthorizationError,
    DepositConflictError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    DepositNotFoundError,
    DepositSnapshot,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
)
from test_deposit_migration import deposit_actor, financial_database_url, runtime_database_url
from test_deposit_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_termination_deposit_migration import history, setup_deposits, terminate


def ready_command(
    database_url: str,
    *,
    legacy: bool = False,
) -> tuple[PostgresDepositService, RecordDepositDispositionCommand]:
    human, prop, lease, security, _, day = setup_deposits(database_url)
    terminate(database_url, human, prop, lease, day)
    return (
        PostgresDepositService(financial_database_url(), prop, human),
        RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            security,
            lease,
            12_000,
            day,
            "Approved BR-DEP-023 disposition",
            context=None if legacy else disposition_context(database_url, security),
        ),
    )


@pytest.mark.parametrize("case", ["identical", "same_deposit_conflict", "other_deposit_conflict"])
def test_concurrent_lease_disposition_identity_is_serialized_and_atomic(
    migrated_database_url: str, case: str
) -> None:
    service, command = ready_command(migrated_database_url)
    second = command
    if case == "same_deposit_conflict":
        second = replace(command, disposition_id=uuid4(), amount_usd_cents=11_000)
    elif case == "other_deposit_conflict":
        other_service, other = ready_command(migrated_database_url)
        assert other_service.property_id == service.property_id
        second = replace(other, idempotency_key=command.idempotency_key)
    actor = deposit_actor(service.actor_id, service.property_id)
    name = "lease-deposit-guard-" + uuid4().hex
    observed_service = replace(
        service,
        financial_database_url=make_conninfo(service.financial_database_url, application_name=name),
    )
    barrier = Barrier(2)

    def run(value: RecordDepositDispositionCommand) -> DepositSnapshot | str:
        barrier.wait(timeout=5)
        try:
            return record_disposition_as_owner(observed_service, value, actor=actor)
        except DepositIdempotencyKeyReused:
            return "conflicting_identity"

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute(
            "SELECT id FROM app.deposits WHERE id IN (%s,%s) ORDER BY id FOR UPDATE",
            (command.deposit_id, second.deposit_id),
        ).fetchall()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run, value) for value in (command, second)]
            try:
                deadline = time.monotonic() + 2
                waiting = 0
                with psycopg.connect(migrated_database_url, autocommit=True) as observation:
                    while waiting < 2 and time.monotonic() < deadline:
                        row = observation.execute(
                            "SELECT count(DISTINCT locks.pid) FROM pg_catalog.pg_locks locks "
                            "JOIN pg_catalog.pg_stat_activity activity ON activity.pid=locks.pid "
                            "WHERE activity.application_name=%s AND NOT locks.granted",
                            (name,),
                        ).fetchone()
                        assert row is not None
                        waiting = int(row[0])
                        if waiting < 2:
                            time.sleep(0.02)
                assert waiting == 2, "Both requests must overlap before source locks are released"
            finally:
                blocker.rollback()
            results = [future.result(timeout=8) for future in futures]
    snapshots = [value for value in results if isinstance(value, DepositSnapshot)]
    if case == "identical":
        assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
    else:
        assert len(snapshots) == 1 and results.count("conflicting_identity") == 1
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT count(*),sum(amount_usd_cents) FROM app.deposit_dispositions "
            "WHERE id IN (%s,%s)",
            (command.disposition_id, second.disposition_id),
        ).fetchone()
        assert row is not None and row[0] == 1 and row[1] in (11_000, 12_000)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_commands WHERE actor_id=%s AND property_id=%s "
            "AND action='deposit.disposition.record' AND idempotency_key=%s",
            (service.actor_id, service.property_id, command.idempotency_key),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_type='deposit_disposition' "
            "AND entity_id IN (%s,%s)",
            (command.disposition_id, second.disposition_id),
        ).fetchone() == (1,)


@pytest.mark.parametrize("already_recorded", [False, True])
def test_disabled_lease_disposition_actor_is_rechecked_before_write_and_replay(
    migrated_database_url: str, already_recorded: bool
) -> None:
    service, command = ready_command(migrated_database_url)
    actor = deposit_actor(service.actor_id, service.property_id)
    original = (
        record_disposition_as_owner(service, command, actor=actor) if already_recorded else None
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (service.actor_id,),
        )
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    with pytest.raises(DepositAuthorizationError):
        record_disposition_as_owner(service, command, actor=actor)
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='active' WHERE actor_id=%s",
            (service.actor_id,),
        )
    result = record_disposition_as_owner(service, command, actor=actor)
    if original is not None:
        assert result == original
    assert result.deposit_disposition_id == command.disposition_id


def test_lease_disposition_property_and_balance_failures_leave_no_effects(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    wrong = replace(service, property_id=uuid4())
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    with pytest.raises(DepositNotFoundError):
        record_disposition_as_owner(
            wrong, command, actor=deposit_actor(service.actor_id, wrong.property_id)
        )
    with pytest.raises(DepositInvalidError):
        record_disposition_as_owner(
            service,
            replace(command, amount_usd_cents=50_001),
            actor=deposit_actor(service.actor_id, service.property_id),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before


def test_lease_disposition_audit_conflict_rolls_back_financial_and_command_rows(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        prior = connection.execute(
            "SELECT id FROM app.audit_events WHERE property_id=%s ORDER BY occurred_at,id LIMIT 1",
            (service.property_id,),
        ).fetchone()
        assert prior is not None
        before = history(connection)
    with pytest.raises(DepositConflictError):
        record_disposition_as_owner(
            service,
            replace(command, disposition_id=prior[0]),
            actor=deposit_actor(service.actor_id, service.property_id),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before


def test_forward56_preserves_all55_history_and_original_successful_replay(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert migrated_database_url
    signature = (
        "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,"
        "bigint,date,text,text)"
    )
    query = (
        "SELECT p.oid,pg_catalog.pg_get_functiondef(p.oid),p.proacl::text,p.proowner,"
        "p.prosecdef,p.provolatile,p.proisstrict,p.proparallel,p.proconfig "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    with (
        _temporary_migration_database("lease_deposit_guards_upgrade") as temporary,
        monkeypatch.context() as environment,
    ):
        temporary_name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv(
            "APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=temporary_name)
        )
        environment.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=temporary_name)
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_55")
        service, command = ready_command(temporary, legacy=True)
        actor = deposit_actor(service.actor_id, service.property_id)
        original = record_disposition_as_owner(service, command, actor=actor)
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            functions = {row[0]: row[1:] for row in connection.execute(query)}
            target = connection.execute("SELECT %s::regprocedure::oid", (signature,)).fetchone()
            assert target is not None
        alembic_command.upgrade(config, "20260914_56")
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before
            after = {row[0]: row[1:] for row in connection.execute(query)}
            assert after.keys() == functions.keys()
            assert all(after[oid] == value for oid, value in functions.items() if oid != target[0])
            assert after[target[0]][1:] == functions[target[0]][1:]
            assert after[target[0]][0] != functions[target[0]][0]
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260914_56",
            )
            assert connection.execute(
                "SELECT has_function_privilege('prm_financial',%s,'EXECUTE'),"
                "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
                "has_function_privilege('prm_bootstrap',%s,'EXECUTE')",
                (signature, signature, signature),
            ).fetchone() == (True, False, False)
        reverse_disposition_as_owner(
            service,
            ReverseDepositDispositionCommand(
                uuid4(),
                uuid4(),
                command.disposition_id,
                "Approved correction",
                "Synthetic reviewed evidence",
            ),
            actor=actor,
        )
        with psycopg.connect(temporary) as connection:
            after_reversal = history(connection)
        assert record_disposition_as_owner(service, command, actor=actor) == original
        with psycopg.connect(temporary) as connection:
            assert history(connection) == after_reversal
