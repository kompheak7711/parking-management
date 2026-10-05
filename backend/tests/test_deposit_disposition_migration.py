"""Real approved source, immutable intent, stale observations and atomic posting."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from lease_deposit_forfeiture_test_support import (
    forfeit_through_draft,
    owner_database_url,
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    DepositConflictError,
    DepositInvalidError,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
    deposit_request_digest,
)
from property_rental.deposit_disposition import (
    DepositDispositionRule,
    LeaseDepositDispositionContext,
)
from property_rental.refund import ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_deposit_migration import (
    deposit_actor,
    financial_database_url,
    runtime_database_url,
    seed_historical_deposit_receipt,
)
from test_deposit_migration import migrated_database_url as migrated_database_url
from test_lease_deposit_command_guards_migration import ready_command
from test_migrations import _temporary_migration_database
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import corrections, refund_id, returned
from test_refund_service_migration import service as refund_service
from test_termination_deposit_migration import history, setup_deposits, terminate


def parameters(
    service: PostgresDepositService, command: RecordDepositDispositionCommand
) -> tuple[object, ...]:
    return (
        service.property_id,
        service.actor_id,
        command.idempotency_key,
        deposit_request_digest("deposit.disposition.record", command),
        command.disposition_id,
        command.deposit_id,
        command.governing_lease_id,
        command.amount_usd_cents,
        command.effective_date,
        command.reason,
        command.authorization_reference,
    )


def raw_context(
    connection: Connection[tuple[object, ...]],
    service: PostgresDepositService,
    command: RecordDepositDispositionCommand,
) -> object:
    assert command.context is not None
    row = connection.execute(
        "SELECT app.record_lease_deposit_disposition_with_context("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            *parameters(service, command),
            command.context.termination_event_id,
            command.context.governing_rule,
            command.context.expected_state_version,
        ),
    ).fetchone()
    assert row is not None
    return row[0]


def prepare_receipt_capacity(
    database_url: str,
    service: PostgresDepositService,
    command: RecordDepositDispositionCommand,
) -> RecordDepositDispositionCommand:
    """Capture the baseline only after a genuine approved requirement adjustment."""
    assert command.context is not None
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            command.deposit_id,
            DepositAdjustmentType.INCREASE,
            1000,
            command.effective_date,
            "Approved synthetic receipt capacity adjustment",
        ),
        actor=deposit_actor(service.actor_id, service.property_id),
    )
    fresh = disposition_context(database_url, command.deposit_id)
    assert fresh.expected_state_version == command.context.expected_state_version + 1
    return replace(command, context=fresh)


def test_voluntary_security_context_links_exact_original_event_command_and_audit(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    # V1-056 slice 6: the forfeiture is a draft confirmed under financial.approve; it forfeits
    # the whole held Security Deposit (BR-DEP-026), so nothing stays held.
    original = forfeit_through_draft(
        service,
        command.deposit_id,
        disposition_id=command.disposition_id,
        idempotency_key=command.idempotency_key,
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            (
                "SELECT context.termination_event_id,context.governing_rule,c"
                "ontext.expected_state_version,command.result_snapshot,audit."
                "resulting_state FROM app.lease_deposit_disposition_contexts "
                "context JOIN app.deposit_commands command ON "
                "command.property_id=context.property_id AND "
                "command.actor_id=context.actor_id AND "
                "command.action=context.action AND "
                "command.idempotency_key=context.idempotency_key JOIN "
                "app.audit_events audit ON audit.id=context.disposition_id "
                "WHERE context.disposition_id=%s"
            ),
            (command.disposition_id,),
        ).fetchone()
        assert row is not None and command.context is not None
        assert row[:3] == (
            command.context.termination_event_id,
            "BR-DEP-023",
            command.context.expected_state_version,
        )
        assert row[3] == row[4]
        before = history(connection)
    assert original.held_refundable_usd_cents == 0
    assert original.deposit_disposition_id == command.disposition_id
    assert (
        forfeit_through_draft(
            service,
            command.deposit_id,
            disposition_id=command.disposition_id,
            idempotency_key=command.idempotency_key,
        )
        == original
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before


@pytest.mark.parametrize("kind", ["SECURITY", "PET"])
def test_explicit_pet_noncompliance_source_supports_each_applicable_deposit(
    migrated_database_url: str,
    kind: str,
) -> None:
    human, prop, lease, security, pet, day = setup_deposits(migrated_database_url)
    service = PostgresDepositService(financial_database_url(), prop, human)
    if kind == "PET":
        seed_historical_deposit_receipt(
            migrated_database_url, deposit_id=pet, actor_id=human, amount_usd_cents=5000
        )
    event = terminate_for_disposition(migrated_database_url, service, lease, day)
    deposit = security if kind == "SECURITY" else pet
    context = disposition_context(migrated_database_url, deposit)
    assert (
        context.termination_event_id == event
        and context.governing_rule is DepositDispositionRule.PET_NONCOMPLIANCE
    )
    # V1-056 slice 6: the forfeiture is a draft confirmed under financial.approve; it forfeits
    # the whole held Deposit (BR-DEP-022), so nothing stays held.
    disposition = uuid4()
    result = forfeit_through_draft(
        service, deposit, disposition_id=disposition, reason="Approved original BR-DEP-022 decision"
    )
    assert result.held_refundable_usd_cents == 0
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT termination_event_id,governing_rule,amount_usd_cents "
            "FROM app.lease_deposit_disposition_contexts WHERE disposition_id=%s",
            (disposition,),
        ).fetchone() == (event, "BR-DEP-022", 50000 if kind == "SECURITY" else 5000)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.lease_termination_warning_sources WHERE command_event_id=%s",
            (event,),
        ).fetchone() == (3,)


@pytest.mark.parametrize(
    "case",
    [
        "voluntary_pet",
        "generic_signed_source",
        "wrong_rule",
        "wrong_event",
        "wrong_lease",
        "wrong_date",
    ],
)
def test_unsupported_source_rule_or_relationship_rejects_without_financial_effects(
    migrated_database_url: str,
    case: str,
) -> None:
    human, prop, lease, security, pet, day = setup_deposits(migrated_database_url)
    service = PostgresDepositService(financial_database_url(), prop, human)
    event = terminate(
        migrated_database_url, human, prop, lease, day, voluntary=case != "generic_signed_source"
    )
    context = LeaseDepositDispositionContext(event, DepositDispositionRule.VOLUNTARY_SECURITY, 1)
    with psycopg.connect(migrated_database_url) as connection:
        value = connection.execute(
            "SELECT app.deposit_disposition_state_version(%s)", (security,)
        ).fetchone()
        assert value is not None and type(value[0]) is int
    context = replace(context, expected_state_version=value[0])
    command = RecordDepositDispositionCommand(
        uuid4(), uuid4(), security, lease, 1000, day, "Approved decision", context=context
    )
    if case == "voluntary_pet":
        command = replace(
            command, deposit_id=pet, context=disposition_context(migrated_database_url, pet)
        )
    elif case in ("generic_signed_source", "wrong_rule"):
        command = replace(
            command,
            context=replace(context, governing_rule=DepositDispositionRule.PET_NONCOMPLIANCE),
        )
    elif case == "wrong_event":
        other_service, other = ready_command(migrated_database_url)
        assert other_service.property_id == prop and other.context is not None
        command = replace(
            command,
            context=replace(context, termination_event_id=other.context.termination_event_id),
        )
    elif case == "wrong_lease":
        _, other = ready_command(migrated_database_url)
        command = replace(command, governing_lease_id=other.governing_lease_id)
    elif case == "wrong_date":
        command = replace(command, effective_date=day + timedelta(days=1))
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    with pytest.raises(DepositInvalidError):
        record_disposition_as_owner(service, command, actor=deposit_actor(human, prop))
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before


def test_old_fresh_entry_and_direct_storage_require_context_without_changing_history(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    with pytest.raises(DepositInvalidError):
        record_disposition_as_owner(
            service,
            replace(command, context=None),
            actor=deposit_actor(service.actor_id, service.property_id),
        )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as denied:
            connection.execute(
                (
                    "INSERT INTO app.deposit_dispositions(id,deposit_id,amount_us"
                    "d_cents,governing_lease_id,effective_date,reason,occurred_at"
                    ",actor_id,authorization_reference) "
                    "VALUES(%s,%s,1000,%s,%s,'Approved',statement_timestamp(),%s,"
                    "'deposits.dispose')"
                ),
                (
                    command.disposition_id,
                    command.deposit_id,
                    command.governing_lease_id,
                    command.effective_date,
                    service.actor_id,
                ),
            )
        assert denied.value.sqlstate == "22023"
        connection.rollback()
        assert history(connection) == before


@pytest.mark.parametrize("change", ["required", "receipt", "disposition"])
def test_net_zero_history_invalidates_fresh_posting_even_when_balance_is_restored(
    migrated_database_url: str,
    change: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    if change == "receipt":
        command = prepare_receipt_capacity(migrated_database_url, service, command)
    actor = deposit_actor(service.actor_id, service.property_id)
    if change == "required":
        for kind in (DepositAdjustmentType.INCREASE, DepositAdjustmentType.DECREASE):
            service.adjust_required_amount(
                AdjustDepositRequiredAmountCommand(
                    uuid4(),
                    uuid4(),
                    command.deposit_id,
                    kind,
                    1000,
                    command.effective_date,
                    "Approved correction",
                ),
                actor=actor,
            )
    elif change == "receipt":
        receipt = seed_historical_deposit_receipt(
            migrated_database_url,
            deposit_id=command.deposit_id,
            actor_id=service.actor_id,
            amount_usd_cents=1000,
        )
        reverse_receipt_as_owner(
            service,
            ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Approved correction"),
            actor=actor,
        )
    else:
        fresh = replace(command, idempotency_key=uuid4(), disposition_id=uuid4())
        record_disposition_as_owner(service, fresh, actor=actor)
        reverse_disposition_as_owner(
            service,
            ReverseDepositDispositionCommand(
                uuid4(), uuid4(), fresh.disposition_id, "Approved correction", "Synthetic review"
            ),
            actor=actor,
        )
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    with pytest.raises(DepositConflictError):
        record_disposition_as_owner(service, command, actor=actor)
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before
    refreshed = replace(
        command, context=disposition_context(migrated_database_url, command.deposit_id)
    )
    assert (
        record_disposition_as_owner(service, refreshed, actor=actor).held_refundable_usd_cents
        == 38000
    )


@pytest.mark.parametrize("change", ["refund", "return", "return_reversal"])
def test_refund_history_participates_in_posting_observation(
    migrated_database_url: str,
    change: str,
) -> None:
    human, prop, _, lease, pet, review = qualified(migrated_database_url)
    service = PostgresDepositService(financial_database_url(), prop, human)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT app.deposit_disposition_state_version(%s),current_date", (pet,)
        ).fetchone()
        assert row is not None and type(row[0]) is int and type(row[1]) is date
        version, day = row[0], row[1]
    original = create_pet_refund(
        refund_service(),
        prop,
        pet_refund_command(pet, review, 10000),
        actor=refund_actor(human, prop, "refunds.create"),
    )
    if change != "refund":
        with psycopg.connect(migrated_database_url) as connection:
            row = connection.execute(
                "SELECT app.deposit_disposition_state_version(%s)", (pet,)
            ).fetchone()
            assert row is not None and type(row[0]) is int
            version = row[0]
        corrected = refund_service().verify_usd_return(
            prop,
            refund_id(original),
            returned(10000),
            actor=refund_actor(human, prop, "refunds.correct"),
        )
        if change == "return_reversal":
            with psycopg.connect(migrated_database_url) as connection:
                row = connection.execute(
                    "SELECT app.deposit_disposition_state_version(%s)", (pet,)
                ).fetchone()
                assert row is not None and type(row[0]) is int
                version = row[0]
            refund_service().reverse_correction(
                prop,
                refund_id(original),
                UUID(str(corrections(corrected)[0]["id"])),
                ReverseRefundCorrectionCommand(
                    uuid4(), "Synthetic evidence", "Approved correction"
                ),
                actor=refund_actor(human, prop, "refunds.corrections.reverse"),
            )
    event = terminate_for_disposition(migrated_database_url, service, lease, day)
    context = LeaseDepositDispositionContext(
        event, DepositDispositionRule.PET_NONCOMPLIANCE, version
    )
    command = RecordDepositDispositionCommand(
        uuid4(), uuid4(), pet, lease, 1000, day, "Approved BR-DEP-022 source", context=context
    )
    with pytest.raises(DepositConflictError):
        record_disposition_as_owner(service, command, actor=deposit_actor(human, prop))
    fresh = replace(command, context=disposition_context(migrated_database_url, pet))
    assert (
        record_disposition_as_owner(
            service, fresh, actor=deposit_actor(human, prop)
        ).deposit_disposition_id
        == command.disposition_id
    )


@pytest.mark.parametrize("event", ["required", "receipt"])
def test_repeatable_read_cannot_post_against_an_observation_before_concurrent_commit(
    migrated_database_url: str,
    event: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    if event == "receipt":
        command = prepare_receipt_capacity(migrated_database_url, service, command)
    with psycopg.connect(owner_database_url(financial_database_url())) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        stale.execute("SELECT app.deposit_snapshot(%s)", (command.deposit_id,)).fetchone()
        if event == "required":
            service.adjust_required_amount(
                AdjustDepositRequiredAmountCommand(
                    uuid4(),
                    uuid4(),
                    command.deposit_id,
                    DepositAdjustmentType.INCREASE,
                    1000,
                    command.effective_date,
                    "Concurrent approved correction",
                ),
                actor=deposit_actor(service.actor_id, service.property_id),
            )
        else:
            seed_historical_deposit_receipt(
                migrated_database_url,
                deposit_id=command.deposit_id,
                actor_id=service.actor_id,
                amount_usd_cents=1000,
            )
        with psycopg.connect(migrated_database_url) as owner:
            before = history(owner)
        with pytest.raises(psycopg.errors.SerializationFailure):
            raw_context(stale, service, command)
        stale.rollback()
    with psycopg.connect(migrated_database_url) as owner:
        assert history(owner) == before


def test_two_fresh_commands_cannot_both_consume_one_financial_observation(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    command = replace(command, amount_usd_cents=40000)
    barrier = Barrier(2)

    def run(value: RecordDepositDispositionCommand) -> str:
        barrier.wait(timeout=5)
        try:
            record_disposition_as_owner(
                service, value, actor=deposit_actor(service.actor_id, service.property_id)
            )
        except DepositConflictError:
            return "stale"
        return "posted"

    second = replace(command, idempotency_key=uuid4(), disposition_id=uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, (command, second))) == ["posted", "stale"]


@pytest.mark.parametrize("index", [4, 5, 6, 7, 8, 9, 11, 12, 13])
def test_raw_replay_rejects_changed_fields_even_with_the_old_digest(
    migrated_database_url: str,
    index: int,
) -> None:
    service, command = ready_command(migrated_database_url)
    record_disposition_as_owner(
        service, command, actor=deposit_actor(service.actor_id, service.property_id)
    )
    assert command.context is not None
    params = [
        *parameters(service, command),
        command.context.termination_event_id,
        command.context.governing_rule,
        command.context.expected_state_version,
    ]
    changes: dict[int, object] = {
        4: uuid4(),
        5: uuid4(),
        6: uuid4(),
        7: 12001,
        8: command.effective_date + timedelta(days=1),
        9: "Changed reason",
        11: uuid4(),
        12: "BR-DEP-022",
        13: command.context.expected_state_version + 1,
    }
    params[index] = changes[index]
    with psycopg.connect(migrated_database_url) as owner:
        before = history(owner)
    with psycopg.connect(owner_database_url(financial_database_url())) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "SELECT app.record_lease_deposit_disposition_with_context("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                params,
            )
    with psycopg.connect(migrated_database_url) as owner:
        assert history(owner) == before


def test_immediate_constraints_and_transaction_rollback_preserve_atomic_history(
    migrated_database_url: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    with psycopg.connect(migrated_database_url) as owner:
        before = history(owner)
    with psycopg.connect(owner_database_url(financial_database_url())) as connection:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert isinstance(raw_context(connection, service, command), dict)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.rollback()
    with psycopg.connect(migrated_database_url) as owner:
        assert history(owner) == before
    assert (
        record_disposition_as_owner(
            service, command, actor=deposit_actor(service.actor_id, service.property_id)
        ).deposit_disposition_id
        == command.disposition_id
    )


@pytest.mark.parametrize("role", ["prm_runtime", "prm_financial", "prm_bootstrap"])
def test_context_is_append_only_and_only_financial_role_has_the_narrow_wrapper(
    migrated_database_url: str,
    role: str,
) -> None:
    service, command = ready_command(migrated_database_url)
    record_disposition_as_owner(
        service, command, actor=deposit_actor(service.actor_id, service.property_id)
    )
    wrapper = (
        "app.record_lease_deposit_disposition_with_context(uuid,uuid,"
        "uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,big"
        "int)"
    )
    helper = (
        "app.require_lease_deposit_disposition_context(uuid,uuid,uuid"
        ",text,uuid,uuid,uuid,bigint,date,text,text)"
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            (
                "SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_"
                "privilege(%s,%s,'EXECUTE'),has_table_privilege(%s,'app.lease"
                "_deposit_disposition_contexts','SELECT,INSERT,UPDATE,DELETE,"
                "TRUNCATE')"
            ),
            (role, wrapper, role, helper, role),
            # V1-056 slice 6 (owner answer to Q-2026-10-04-12): the financial role lost EXECUTE
            # on the wrapper too; only the forfeiture draft confirm runs it, as the owner.
        ).fetchone() == (False, False, False)
        for query in (
            (
                "UPDATE app.lease_deposit_disposition_contexts SET "
                "reason='Changed' WHERE disposition_id=%s"
            ),
            "DELETE FROM app.lease_deposit_disposition_contexts WHERE disposition_id=%s",
        ):
            with pytest.raises(psycopg.Error) as denied:
                connection.execute(query, (command.disposition_id,))
            assert denied.value.sqlstate == "55000"
            connection.rollback()
        with pytest.raises(psycopg.Error) as denied:
            connection.execute("TRUNCATE app.lease_deposit_disposition_contexts")
        assert denied.value.sqlstate == "55000"


def test_forward58_preserves_all57_history_function_identity_and_legacy_replay(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert migrated_database_url
    query = (
        "SELECT p.oid,pg_get_functiondef(p.oid),p.proacl::text,p.proo"
        "wner,p.prosecdef,p.provolatile,p.proisstrict,p.proparallel,p"
        ".proconfig FROM pg_proc p JOIN pg_namespace n ON "
        "n.oid=p.pronamespace WHERE n.nspname='app' AND "
        "p.prokind='f' ORDER BY p.oid"
    )
    signatures = (
        (
            "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uui"
            "d,uuid,uuid,bigint,date,text,text)"
        ),
        "app.validate_deposit_required_adjustment()",
    )
    with (
        _temporary_migration_database("disposition_context_upgrade") as temporary,
        monkeypatch.context() as environment,
    ):
        name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv("APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=name))
        environment.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=name)
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_57")
        service, command = ready_command(temporary, legacy=True)
        actor = deposit_actor(service.actor_id, service.property_id)
        original = record_disposition_as_owner(service, command, actor=actor)
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            functions = {row[0]: row[1:] for row in connection.execute(query)}
            changed: set[object] = set()
            for signature in signatures:
                row = connection.execute("SELECT %s::regprocedure::oid", (signature,)).fetchone()
                assert row is not None
                changed.add(row[0])
        alembic_command.upgrade(config, "20260914_58")
        with psycopg.connect(temporary) as connection:
            after = history(connection)
            assert {k: after[k] for k in before} == before
            assert set(after) - before.keys() == {"lease_deposit_disposition_contexts"}
            assert after["lease_deposit_disposition_contexts"] == []
            latest = {row[0]: row[1:] for row in connection.execute(query)}
            assert len(latest.keys() - functions.keys()) == 3
            assert all(
                latest[oid] == value for oid, value in functions.items() if oid not in changed
            )
            assert all(
                latest[oid][1:] == functions[oid][1:] and latest[oid][0] != functions[oid][0]
                for oid in changed
            )
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260914_58",
            )
        reverse_disposition_as_owner(
            service,
            ReverseDepositDispositionCommand(
                uuid4(),
                uuid4(),
                command.disposition_id,
                "Approved historical correction",
                "Synthetic evidence",
            ),
            actor=actor,
        )
        with psycopg.connect(temporary) as connection:
            before_replay = history(connection)
        assert record_disposition_as_owner(service, command, actor=actor) == original
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before_replay
