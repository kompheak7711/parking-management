"""A financial observation follows immutable events, not net value or lock probes."""

from datetime import date
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deposit_disposition_test_support import disposition_context
from lease_deposit_forfeiture_test_support import (
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
    deposit_request_digest,
)
from property_rental.refund import ReverseRefundCorrectionCommand
from property_rental.termination_deposit import (
    PostgresTerminationDepositReadService,
    TerminationDepositBalance,
)
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_deposit_migration import (
    deposit_actor,
    financial_database_url,
    runtime_database_url,
    seed_historical_deposit_receipt,
)
from test_deposit_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import setup_move_in
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import corrections, refund_id, returned, service
from test_termination_deposit_migration import history, reader_actor, setup_deposits, terminate


def observe(human: UUID, prop: UUID, lease: UUID, deposit: UUID) -> TerminationDepositBalance:
    result = PostgresTerminationDepositReadService(runtime_database_url(), prop).get(
        lease, actor=reader_actor(human, prop)
    )
    assert result.financial_completion_assessed is False
    return next(row for row in result.deposits if row.deposit_id == deposit)


def adjustment(
    deposit: UUID, day: date, *, decrease: bool = False
) -> AdjustDepositRequiredAmountCommand:
    return AdjustDepositRequiredAmountCommand(
        uuid4(),
        uuid4(),
        deposit,
        DepositAdjustmentType.DECREASE if decrease else DepositAdjustmentType.INCREASE,
        1000,
        day,
        "Synthetic approved signed-term correction",
    )


def revision(connection: Connection[tuple[object, ...]], deposit: UUID) -> int:
    row = connection.execute(
        "SELECT app.deposit_disposition_state_version(%s)", (deposit,)
    ).fetchone()
    assert row is not None and type(row[0]) is int
    return row[0]


def test_required_corrections_and_receipt_reversal_advance_even_at_original_net_value(
    migrated_database_url: str,
) -> None:
    human, prop, lease, security, pet, day = setup_deposits(migrated_database_url)
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    authority = deposit_actor(human, prop)
    initial = observe(human, prop, lease, pet)
    separate = observe(human, prop, lease, security)
    assert initial.disposition_state_version == initial.version
    command = adjustment(pet, day)
    original = deposits.adjust_required_amount(command, actor=authority)
    increased = observe(human, prop, lease, pet)
    assert increased.disposition_state_version == initial.disposition_state_version + 1
    assert increased.required_usd_cents == initial.required_usd_cents + 1000
    assert deposits.adjust_required_amount(command, actor=authority) == original
    assert observe(human, prop, lease, pet) == increased
    deposits.adjust_required_amount(adjustment(pet, day, decrease=True), actor=authority)
    restored = observe(human, prop, lease, pet)
    assert restored.required_usd_cents == initial.required_usd_cents
    assert restored.disposition_state_version == initial.disposition_state_version + 2
    receipt = seed_historical_deposit_receipt(
        migrated_database_url, deposit_id=pet, actor_id=human, amount_usd_cents=5000
    )
    paid = observe(human, prop, lease, pet)
    assert paid.disposition_state_version == initial.disposition_state_version + 3
    assert paid.received_usd_cents == paid.held_refundable_usd_cents == 5000
    reversal = ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Synthetic correction")
    replay = deposits.reverse_receipt(reversal, actor=authority)
    corrected = observe(human, prop, lease, pet)
    assert corrected.disposition_state_version == initial.disposition_state_version + 4
    assert corrected.received_usd_cents == corrected.held_refundable_usd_cents == 0
    assert corrected.version == initial.version
    assert deposits.reverse_receipt(reversal, actor=authority) == replay
    assert observe(human, prop, lease, pet) == corrected
    assert observe(human, prop, lease, security) == separate


def test_disposition_reversal_and_exact_replay_keep_separate_observation_and_saved_result(
    migrated_database_url: str,
) -> None:
    human, prop, lease, security, _, day = setup_deposits(migrated_database_url)
    terminate(migrated_database_url, human, prop, lease, day)
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    authority = deposit_actor(human, prop)
    before = observe(human, prop, lease, security)
    command = RecordDepositDispositionCommand(
        uuid4(),
        uuid4(),
        security,
        lease,
        12000,
        day,
        "Approved BR-DEP-023 synthetic disposition",
        context=disposition_context(migrated_database_url, security),
    )
    original = record_disposition_as_owner(deposits, command, actor=authority)
    posted = observe(human, prop, lease, security)
    assert posted.disposition_state_version == before.disposition_state_version + 1
    assert posted.held_refundable_usd_cents == before.held_refundable_usd_cents - 12000
    reverse_disposition_as_owner(
        deposits,
        ReverseDepositDispositionCommand(
            uuid4(),
            uuid4(),
            command.disposition_id,
            "Synthetic correction",
            "Reviewed synthetic evidence",
        ),
        actor=authority,
    )
    restored = observe(human, prop, lease, security)
    assert restored.held_refundable_usd_cents == before.held_refundable_usd_cents
    assert restored.disposition_state_version == before.disposition_state_version + 2
    assert restored.version == original.version == before.version
    with psycopg.connect(migrated_database_url) as connection:
        all_history = history(connection)
    assert record_disposition_as_owner(deposits, command, actor=authority) == original
    assert observe(human, prop, lease, security) == restored
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == all_history


def test_refund_return_and_correction_reversal_advance_without_changing_old_replay(
    migrated_database_url: str,
) -> None:
    human, prop, _, lease, pet, review = qualified(migrated_database_url)
    before = observe(human, prop, lease, pet)
    command = pet_refund_command(pet, review, 10000)
    creator = refund_actor(human, prop, "refunds.create")
    original = create_pet_refund(service(), prop, command, actor=creator)
    identity = refund_id(original)
    posted = observe(human, prop, lease, pet)
    assert posted.disposition_state_version == before.disposition_state_version + 1
    assert posted.held_refundable_usd_cents == before.held_refundable_usd_cents - 10000
    corrected = service().verify_usd_return(
        prop, identity, returned(10000), actor=refund_actor(human, prop, "refunds.correct")
    )
    restored = observe(human, prop, lease, pet)
    assert restored.disposition_state_version == before.disposition_state_version + 2
    assert restored.held_refundable_usd_cents == before.held_refundable_usd_cents
    service().reverse_correction(
        prop,
        identity,
        UUID(str(corrections(corrected)[0]["id"])),
        ReverseRefundCorrectionCommand(uuid4(), "Synthetic evidence", "Correction was mistaken"),
        actor=refund_actor(human, prop, "refunds.corrections.reverse"),
    )
    reversed_return = observe(human, prop, lease, pet)
    assert reversed_return.disposition_state_version == before.disposition_state_version + 3
    assert reversed_return.held_refundable_usd_cents == posted.held_refundable_usd_cents
    assert reversed_return.version == before.version
    assert create_pet_refund(service(), prop, command, actor=creator) == original
    assert observe(human, prop, lease, pet) == reversed_return


def test_metadata_link_and_coordination_guard_are_distinct_from_financial_events(
    migrated_database_url: str,
) -> None:
    flow, actor, move, security = setup_move_in(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        before = revision(connection, security)
    flow.complete(move, actor=actor)
    linked = observe(flow.actor_id, flow.property_id, move.lease_id, security)
    assert linked.disposition_state_version == before + 1
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute("SELECT app.serialize_deposit_state(%s)", (security,))
        assert revision(connection, security) == linked.disposition_state_version
        snapshot = connection.execute("SELECT app.deposit_snapshot(%s)", (security,)).fetchone()
        assert snapshot is not None and isinstance(snapshot[0], dict)
        assert "disposition_state_version" not in snapshot[0]
        assert snapshot[0]["version"] == linked.version
    assert observe(flow.actor_id, flow.property_id, move.lease_id, security) == linked


def test_repeatable_read_keeps_revision_and_balance_in_one_committed_observation(
    migrated_database_url: str,
) -> None:
    human, prop, lease, _, pet, day = setup_deposits(migrated_database_url)
    sql_read = "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)->'deposits'"
    with psycopg.connect(runtime_database_url()) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        before = reader.execute(sql_read, (prop, lease, human)).fetchone()
        PostgresDepositService(financial_database_url(), prop, human).adjust_required_amount(
            adjustment(pet, day), actor=deposit_actor(human, prop)
        )
        assert reader.execute(sql_read, (prop, lease, human)).fetchone() == before
    assert before is not None and isinstance(before[0], list)
    prior = next(row for row in before[0] if row["deposit_id"] == str(pet))
    latest = observe(human, prop, lease, pet)
    assert latest.disposition_state_version == prior["disposition_state_version"] + 1
    assert latest.required_usd_cents == prior["required_usd_cents"] + 1000


def test_rolled_back_financial_event_does_not_advance_revision_or_history(
    migrated_database_url: str,
) -> None:
    human, prop, lease, _, pet, day = setup_deposits(migrated_database_url)
    before = observe(human, prop, lease, pet)
    request = adjustment(pet, day)
    with psycopg.connect(migrated_database_url) as owner:
        preserved = history(owner)
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute(
            "SELECT app.adjust_deposit_required_amount(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                human,
                request.idempotency_key,
                deposit_request_digest("deposit.required.adjust", request),
                request.adjustment_id,
                pet,
                request.adjustment_type,
                request.amount_usd_cents,
                request.effective_date,
                request.reason,
                request.authorization_reference,
            ),
        )
        inside = connection.execute(
            "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)->'deposits'",
            (prop, lease, human),
        ).fetchone()
        assert inside is not None and isinstance(inside[0], list)
        row = next(row for row in inside[0] if row["deposit_id"] == str(pet))
        assert row["disposition_state_version"] == before.disposition_state_version + 1
        connection.rollback()
    assert observe(human, prop, lease, pet) == before
    with psycopg.connect(migrated_database_url) as owner:
        assert history(owner) == preserved


@pytest.mark.parametrize("role", ["prm_runtime", "prm_financial", "prm_bootstrap"])
def test_revision_helper_is_private_and_observation_has_no_financial_effect(
    migrated_database_url: str,
    role: str,
) -> None:
    human, prop, lease, _, pet, _ = setup_deposits(migrated_database_url)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT has_function_privilege(%s,'app.deposit_disposition_state_version(uuid)',"
            "'EXECUTE')",
            (role,),
        ).fetchone() == (False,)
        assert owner.execute(
            "SELECT provolatile,prosecdef,proisstrict,proconfig FROM pg_proc WHERE oid="
            "'app.deposit_disposition_state_version(uuid)'::regprocedure"
        ).fetchone() == ("s", True, True, ["search_path=pg_catalog"])
        before = history(owner)
    for _ in range(2):
        assert observe(human, prop, lease, pet).disposition_state_version >= 1
    with psycopg.connect(migrated_database_url) as owner:
        assert history(owner) == before


def test_forward57_preserves_all56_rows_other_functions_and_historical_command_replay(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert migrated_database_url
    query = (
        "SELECT p.oid,pg_get_functiondef(p.oid),p.proacl::text,p.proowner,p.prosecdef,"
        "p.provolatile,p.proisstrict,p.proparallel,p.proconfig FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app' "
        "AND p.prokind='f' ORDER BY p.oid"
    )
    signature = "app.lease_termination_deposit_readiness(uuid,uuid,uuid)"
    with (
        _temporary_migration_database("deposit_revision_upgrade") as temporary,
        monkeypatch.context() as environment,
    ):
        name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv("APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=name))
        environment.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=name)
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_56")
        human, prop, lease, security, _, day = setup_deposits(temporary)
        terminate(temporary, human, prop, lease, day)
        deposits = PostgresDepositService(financial_database_url(), prop, human)
        authority = deposit_actor(human, prop)
        command = RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            security,
            lease,
            12000,
            day,
            "Synthetic approved BR-DEP-023 disposition",
        )
        original = record_disposition_as_owner(deposits, command, actor=authority)
        with psycopg.connect(temporary) as owner:
            before = history(owner)
            functions = {row[0]: row[1:] for row in owner.execute(query)}
            target = owner.execute("SELECT %s::regprocedure::oid", (signature,)).fetchone()
            assert target is not None
            old_read = owner.execute(
                "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)", (prop, lease, human)
            ).fetchone()
        alembic_command.upgrade(config, "20260914_57")
        with psycopg.connect(temporary) as owner:
            assert history(owner) == before
            after = {row[0]: row[1:] for row in owner.execute(query)}
            assert all(after[oid] == value for oid, value in functions.items() if oid != target[0])
            assert after[target[0]][1:] == functions[target[0]][1:]
            assert after[target[0]][0] != functions[target[0]][0]
            assert len(after.keys() - functions.keys()) == 1
            assert owner.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260914_57",
            )
            new_read = owner.execute(
                "SELECT app.lease_termination_deposit_readiness(%s,%s,%s)", (prop, lease, human)
            ).fetchone()
        assert old_read is not None and new_read is not None
        old_payload, new_payload = (
            cast(dict[str, object], old_read[0]),
            cast(dict[str, object], new_read[0]),
        )
        old_payload.pop("observed_at")
        new_payload.pop("observed_at")
        for row in cast(list[dict[str, object]], new_payload["deposits"]):
            assert type(row.pop("disposition_state_version")) is int
        assert new_payload == old_payload
        assert record_disposition_as_owner(deposits, command, actor=authority) == original
        with psycopg.connect(temporary) as owner:
            assert history(owner) == before
        assert observe(human, prop, lease, security).active_disposition_usd_cents == 12000
