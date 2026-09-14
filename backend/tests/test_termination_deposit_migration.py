"""Real source, changing balance, read authorization and forward-upgrade evidence."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import TracebackType
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg import Connection, Cursor, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from property_rental.deposit import (
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import PostgresLeaseService
from property_rental.lease_termination import TerminationBasis
from property_rental.termination_deposit import (
    PostgresTerminationDepositReadService,
    TerminationDepositAuthorizationError,
    TerminationDepositNotFoundError,
)
from test_deposit_migration import (
    create_pet,
    deposit_actor,
    financial_database_url,
    runtime_database_url,
    seed_historical_deposit_receipt,
    setup_signed_pet_lease,
)
from test_deposit_migration import migrated_database_url as migrated_database_url
from test_lease_termination import context_without_notice
from test_lease_termination_migration import termination_actor, termination_command
from test_migrations import _temporary_migration_database
from test_move_in_migration import setup_move_in


def reader_actor(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(name, frozenset({str(prop)}))
            for name in ("leases.read", "deposits.read")
        ),
    )


def setup_deposits(database_url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, date]:
    flow, actor, move, security = setup_move_in(database_url)
    flow.complete(move, actor=actor)
    day = move.actual_move_in_date
    with psycopg.connect(database_url) as connection:
        approval = uuid4()
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Synthetic approved pet',clock_timestamp(),%s)",
            (approval, move.lease_id, day, flow.actor_id),
        )
    deposits = PostgresDepositService(financial_database_url(), flow.property_id, flow.actor_id)
    pet, _ = create_pet(
        deposits, deposit_actor(flow.actor_id, flow.property_id), move.lease_id, approval, day
    )
    return flow.actor_id, flow.property_id, move.lease_id, security, pet, day


def terminate(
    database_url: str, human: UUID, prop: UUID, lease: UUID, day: date, *, voluntary: bool = True
) -> UUID:
    context = (
        context_without_notice()
        if voluntary
        else context_without_notice(basis=TerminationBasis.SIGNED_LEASE_OTHER)
    )
    with psycopg.connect(database_url) as connection:
        command = termination_command(
            connection,
            lease,
            actual_date=day,
            context=context,
            governing="BR-LEASE-021" if voluntary else "Signed Lease approved other grounds",
        )
    PostgresLeaseService(runtime_database_url(), prop, human).terminate(
        command, actor=termination_actor(human, prop)
    )
    return command.event_id


def history(connection: Connection[tuple[object, ...]]) -> dict[str, list[tuple[object, ...]]]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='app' ORDER BY tablename"
        )
    ]
    return {
        table: connection.execute(
            sql.SQL("SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text").format(
                sql.Identifier(table)
            )
        ).fetchall()
        for table in tables
    }


def test_real_termination_separates_security_and_pet_without_posting_or_physical_changes(
    migrated_database_url: str,
) -> None:
    human, prop, lease, security, pet, day = setup_deposits(migrated_database_url)
    service = PostgresTerminationDepositReadService(runtime_database_url(), prop)
    actor = reader_actor(human, prop)
    before = service.get(lease, actor=actor)
    assert before.evidence_status == "NO_TERMINATION"
    assert {d.consequence for d in before.deposits} == {"NOT_TERMINATED"}
    event = terminate(migrated_database_url, human, prop, lease, day)
    with psycopg.connect(migrated_database_url) as connection:
        snapshot = history(connection)
    result = service.get(lease, actor=actor)
    assert (
        result.termination_event_id == event
        and result.evidence_status == "VOLUNTARY_EARLY_VERIFIED"
    )
    rows = {d.deposit_id: d for d in result.deposits}
    assert (
        rows[security].consequence,
        rows[security].business_rule,
        rows[security].held_refundable_usd_cents,
        rows[security].explicit_disposition_pending,
    ) == ("NON_REFUNDABLE_SECURITY", "BR-DEP-023", 50_000, True)
    assert (
        rows[pet].consequence,
        rows[pet].business_rule,
        rows[pet].received_usd_cents,
        rows[pet].outstanding_required_usd_cents,
        rows[pet].explicit_disposition_pending,
    ) == ("SEPARATE_PET_SETTLEMENT", "BR-DEP-024", 0, 20_000, False)
    assert result.currency == "USD" and not result.financial_completion_assessed
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == snapshot


def test_disposition_and_reversal_change_current_readiness_without_completing_finances(
    migrated_database_url: str,
) -> None:
    human, prop, lease, security, _, day = setup_deposits(migrated_database_url)
    terminate(migrated_database_url, human, prop, lease, day)
    read = PostgresTerminationDepositReadService(runtime_database_url(), prop)
    actor = reader_actor(human, prop)
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    authority = deposit_actor(human, prop)
    command = RecordDepositDispositionCommand(
        uuid4(), uuid4(), security, lease, 50_000, day, "Approved BR-DEP-023 Security disposition"
    )
    deposits.record_disposition(command, actor=authority)
    zero = read.get(lease, actor=actor)
    item = next(d for d in zero.deposits if d.deposit_id == security)
    assert (
        item.held_refundable_usd_cents,
        item.active_disposition_usd_cents,
        item.explicit_disposition_pending,
    ) == (0, 50_000, False)
    assert not zero.financial_completion_assessed
    deposits.reverse_disposition(
        ReverseDepositDispositionCommand(
            uuid4(),
            uuid4(),
            command.disposition_id,
            "Approved correction",
            "Synthetic correction evidence",
        ),
        actor=authority,
    )
    reopened = read.get(lease, actor=actor)
    item = next(d for d in reopened.deposits if d.deposit_id == security)
    assert (
        item.held_refundable_usd_cents,
        item.active_disposition_usd_cents,
        item.explicit_disposition_pending,
    ) == (50_000, 0, True)
    assert not reopened.financial_completion_assessed


def test_unreceived_liability_then_later_receipt_and_reversal_are_separate_observations(
    migrated_database_url: str,
) -> None:
    deposits, authority, lease, approval, day = setup_signed_pet_lease(migrated_database_url)
    pet, _ = create_pet(deposits, authority, lease, approval, day)
    with psycopg.connect(migrated_database_url) as connection:
        current = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',statement_timestamp())::date"
        ).fetchone()
        assert current is not None and isinstance(current[0], date)
    terminate(migrated_database_url, deposits.actor_id, deposits.property_id, lease, current[0])
    read = PostgresTerminationDepositReadService(runtime_database_url(), deposits.property_id)
    actor = reader_actor(deposits.actor_id, deposits.property_id)
    initial = read.get(lease, actor=actor).deposits[0]
    assert (
        initial.required_usd_cents,
        initial.received_usd_cents,
        initial.outstanding_required_usd_cents,
    ) == (20_000, 0, 20_000)
    receipt = seed_historical_deposit_receipt(
        migrated_database_url, deposit_id=pet, actor_id=deposits.actor_id, amount_usd_cents=12_000
    )
    paid = read.get(lease, actor=actor).deposits[0]
    assert (
        paid.received_usd_cents,
        paid.held_refundable_usd_cents,
        paid.outstanding_required_usd_cents,
    ) == (12_000, 12_000, 8_000)
    deposits.reverse_receipt(
        ReverseDepositReceiptCommand(
            uuid4(), uuid4(), receipt, "Approved synthetic receipt correction"
        ),
        actor=authority,
    )
    corrected = read.get(lease, actor=actor)
    assert corrected.deposits[0].received_usd_cents == 0
    assert corrected.deposits[0].outstanding_required_usd_cents == 20_000
    assert (
        not corrected.deposits[0].explicit_disposition_pending
        and not corrected.financial_completion_assessed
    )


@pytest.mark.parametrize("real_other_basis", [True, False])
def test_other_or_incomplete_termination_evidence_does_not_invent_forfeiture(
    migrated_database_url: str, real_other_basis: bool
) -> None:
    human, prop, lease, _, _, day = setup_deposits(migrated_database_url)
    event = None
    if real_other_basis:
        event = terminate(migrated_database_url, human, prop, lease, day, voluntary=False)
    else:
        # Synthetic incomplete historical source: the free-form reason is not a command.
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.leases SET status='TERMINATED',terminated_at=clock_timestamp("
                "),actual_termination_date=%s,termination_reason='BR-LEASE-021 voluntary'"
                ",version=version+1,updated_at=clock_timestamp(),updated_by=%s WHERE id=%"
                "s",
                (day, human, lease),
            )
    result = PostgresTerminationDepositReadService(runtime_database_url(), prop).get(
        lease, actor=reader_actor(human, prop)
    )
    assert result.termination_event_id == event
    assert result.evidence_status == "SIGNED_TERMS_REVIEW_REQUIRED"
    assert all(
        d.consequence == "SIGNED_TERMS_REVIEW_REQUIRED"
        and d.business_rule is None
        and not d.explicit_disposition_pending
        for d in result.deposits
    )


def test_current_actor_property_runtime_permissions_and_read_only_transaction(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    human, prop, lease, _, _, _ = setup_deposits(migrated_database_url)
    connect = psycopg.connect
    observed: list[tuple[object, ...]] = []

    class CheckedConnection:
        def __init__(self, raw: Connection[tuple[object, ...]]) -> None:
            self.raw = raw

        def __enter__(self) -> "CheckedConnection":
            self.raw.__enter__()
            return self

        def __exit__(
            self,
            kind: type[BaseException] | None,
            error: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            self.raw.__exit__(kind, error, traceback)

        def execute(
            self, query: str, params: tuple[object, ...] | None = None
        ) -> Cursor[tuple[object, ...]]:
            if query.startswith("SELECT app.lease_termination_deposit_readiness"):
                row = self.raw.execute(
                    "SELECT current_setting('transaction_read_only'),current_setting('transac"
                    "tion_isolation'),current_setting('lock_timeout'),current_setting('statem"
                    "ent_timeout'),current_setting('TimeZone')"
                ).fetchone()
                assert row is not None
                observed.append(row)
            return self.raw.execute(query, params)

    def checked_connect(conninfo: str, *, connect_timeout: int) -> CheckedConnection:
        assert connect_timeout == 3
        return CheckedConnection(connect(conninfo, connect_timeout=connect_timeout))

    monkeypatch.setattr(psycopg, "connect", checked_connect)
    read = PostgresTerminationDepositReadService(runtime_database_url(), prop)
    read.get(lease, actor=reader_actor(human, prop))
    assert observed == [("on", "repeatable read", "3s", "5s", "UTC")]
    monkeypatch.setattr(psycopg, "connect", connect)
    other_property = uuid4()
    with pytest.raises(TerminationDepositNotFoundError):
        PostgresTerminationDepositReadService(runtime_database_url(), other_property).get(
            lease, actor=reader_actor(human, other_property)
        )
    with connect(migrated_database_url) as owner:
        owner.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(TerminationDepositAuthorizationError):
        read.get(lease, actor=reader_actor(human, prop))
    with connect(runtime_database_url()) as runtime:
        assert runtime.execute(
            "SELECT has_function_privilege('prm_runtime','app.lease_termination_depos"
            "it_readiness(uuid,uuid,uuid)','EXECUTE'),has_table_privilege('prm_runtim"
            "e','app.lease_termination_contexts','SELECT'),has_table_privilege('prm_r"
            "untime','app.deposit_dispositions','INSERT')"
        ).fetchone() == (True, False, False)
    with connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT p.provolatile,p.prosecdef,p.proconfig,has_function_privilege('prm"
            "_bootstrap',p.oid,'EXECUTE') FROM pg_catalog.pg_proc p WHERE p.oid='app."
            "lease_termination_deposit_readiness(uuid,uuid,uuid)'::regprocedure"
        ).fetchone() == ("s", True, ["search_path=pg_catalog"], False)


def test_forward55_preserves_all54_history_functions_and_legacy_evidence(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert migrated_database_url
    functions_query = (
        "SELECT p.oid,p.proname,pg_catalog.pg_get_functiondef(p.oid),p.proacl::te"
        "xt,p.proowner,p.prosecdef,p.provolatile,p.proisstrict,p.proparallel,p.pr"
        "oconfig FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oi"
        "d=p.pronamespace WHERE n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    with (
        _temporary_migration_database("termination_deposit_upgrade") as temporary,
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
        alembic_command.upgrade(config, "20260914_53")
        human, prop, lease, _, _, day = setup_deposits(temporary)
        with psycopg.connect(temporary) as connection:
            command = replace(termination_command(connection, lease, actual_date=day), context=None)
        PostgresLeaseService(runtime_database_url(), prop, human).terminate(
            command, actor=termination_actor(human, prop)
        )
        alembic_command.upgrade(config, "20260914_54")
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            functions = {row[0]: row[1:] for row in connection.execute(functions_query)}
        alembic_command.upgrade(config, "20260914_55")
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before
            after = {row[0]: row[1:] for row in connection.execute(functions_query)}
            assert all(after[oid] == data for oid, data in functions.items())
            assert {after[oid][0] for oid in after.keys() - functions.keys()} == {
                "lease_termination_deposit_readiness"
            }
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260914_55",
            )
        # Preserve the revision55 wire contract; the current typed reader requires57.
        with psycopg.connect(runtime_database_url()) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = connection.execute(
                "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)", (prop, lease, human)
            ).fetchone()
            assert row is not None and isinstance(row[0], dict)
            result = row[0]
        assert result["evidence_status"] == "VOLUNTARY_EARLY_VERIFIED"
        assert result["termination_event_id"] == str(command.event_id)
        assert result["financial_completion_assessed"] is False
        assert all("disposition_state_version" not in item for item in result["deposits"])
