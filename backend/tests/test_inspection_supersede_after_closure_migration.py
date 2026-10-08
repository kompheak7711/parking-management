"""Move-out inspection supersede refused after closure (V1-056 sub-slice 10c-2a-4).

BR-MOVEOUT-006, BR-SETTLE-012 and BR-SETTLE-013 (owner answer 2 to Q-2026-10-07-44 and the owner
answer to Q-2026-10-08-49): once a Lease's Final Settlement is closed, every supersede of a
move-out inspection on that Lease is refused (P5S01, a conflict) before anything is written, so
the inspection the closed Settlement relied on never changes. Damage found after closure is a new
inspection that supersedes nothing. The command and its insert trigger read the Settlement row
FOR SHARE after the Lease row lock.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

import test_final_settlement_draft_migration as final_settlement_draft_tests
from property_rental.move_out_inspection import (
    InspectionFinding,
    MoveOutInspectionConflictError,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
    inspection_request_digest,
)
from test_final_settlement_closed_refusal_migration import close
from test_final_settlement_confirm_migration import CONFIRM_SQL, this_month
from test_final_settlement_draft_migration import STAFF, leaving_case, normal_plan, record
from test_final_settlement_migration import one, today
from test_final_settlement_migration import start as start_settlement
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_settlement_correction_plan_migration import (
    SUPERSEDE_CLOSED,
    blocked_on_lease_row,
    closed_case,
)

COMMAND = "app.move_out_inspection_record(uuid,uuid,uuid,uuid,text,jsonb,text)"
SOURCE = "app.validate_move_out_inspection_source()"
RECORD_SQL = "SELECT app.move_out_inspection_record(%s,%s,%s,%s,%s,%s,%s)"
OUTSIDE_READ_COMMITTED = "A move-out inspection is superseded only at READ COMMITTED"


def record_directly(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    command: RecordMoveOutInspection,
    request_id: str,
) -> None:
    """The inspection command called directly in the caller's transaction (the service always
    writes at READ COMMITTED), as the table owner on the Lease's actor."""
    intent = command.intent()
    connection.execute(
        RECORD_SQL,
        (
            case["prop"],
            case["lease"],
            case["human"],
            command.idempotency_key,
            inspection_request_digest(case["prop"], case["lease"], intent),
            Jsonb(intent),
            request_id,
        ),
    )


def inspection_of(url: str, lease: UUID) -> UUID:
    """The Lease's only inspection (the one the Settlement relied on)."""
    return UUID(
        str(one(url, "SELECT id FROM app.move_out_inspections WHERE lease_id=%s", lease)[0])
    )


def inspection(
    url: str, lease: UUID, finding: UUID, *, supersedes: UUID | None = None
) -> RecordMoveOutInspection:
    return RecordMoveOutInspection(
        uuid4(),
        uuid4(),
        int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0])),
        today(url),
        "Later inspection condition",
        "Approved inspection",
        "Evidence-904",
        "Damage found after the Final Settlement",
        (InspectionFinding(finding, "Cracked bathroom tile", False),),
        supersedes_inspection_id=supersedes,
    )


def written(url: str, command: RecordMoveOutInspection) -> tuple[int, int, int, int]:
    """Rows the command would write: inspection, findings, command evidence and audit event."""
    found = one(
        url,
        "SELECT (SELECT count(*) FROM app.move_out_inspections WHERE id=%s),"
        "(SELECT count(*) FROM app.inspection_damage_findings WHERE inspection_id=%s OR id=%s),"
        "(SELECT count(*) FROM app.move_out_inspection_commands WHERE idempotency_key=%s),"
        "(SELECT count(*) FROM app.audit_events WHERE entity_type='move_out_inspection' "
        "AND entity_id=%s)",
        command.inspection_id,
        command.inspection_id,
        command.findings[0].finding_id,
        command.idempotency_key,
        command.inspection_id,
    )
    return (int(found[0]), int(found[1]), int(found[2]), int(found[3]))


def current_effect(url: str, inspection_id: UUID) -> str:
    return str(
        one(url, "SELECT app.move_out_inspection_snapshot(%s)->>'current_effect'", inspection_id)[0]
    )


def refused(failure: pytest.ExceptionInfo[MoveOutInspectionConflictError]) -> tuple[Any, Any]:
    """The database refusal behind the service conflict."""
    error = failure.value.__cause__
    assert isinstance(error, psycopg.Error)
    return error.sqlstate, error.diag.message_primary


def test_a_supersede_after_closure_is_refused_and_the_settlement_s_inspection_stays(
    migrated_database_url: str,
) -> None:
    """A supersede of the inspection a closed Final Settlement relied on is refused as a
    conflict (P5S01) and writes nothing: no inspection, finding, command or audit row; the
    inspection stays current and its pet damage line stays pet damage. Damage found after
    closure is a separate inspection that supersedes nothing; it is accepted, and its finding
    is current next to the earlier one."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, lease = case["prop"], case["human"], case["lease"]
    earlier = inspection_of(url, lease)
    supersede = inspection(url, lease, uuid4(), supersedes=earlier)
    with pytest.raises(MoveOutInspectionConflictError) as failure:
        inspection_flow().record(
            prop,
            lease,
            supersede,
            actor=inspection_actor(human, prop),
            request_id="closed-inspection-supersede",
        )
    assert refused(failure) == ("P5S01", SUPERSEDE_CLOSED)
    assert str(failure.value) == (
        "The Final Settlement is closed; record later damage as a new inspection"
    )
    assert written(url, supersede) == (0, 0, 0, 0)
    assert current_effect(url, earlier) == "INSPECTION_ONLY"
    assert one(url, "SELECT app.invoice_line_is_pet_damage(%s,%s)", case["pet_line"], lease) == (
        True,
    )

    later_finding = uuid4()
    later = inspection(url, lease, later_finding)
    result = inspection_flow().record(
        prop, lease, later, actor=inspection_actor(human, prop), request_id="later-inspection"
    )
    assert result.status_code == 201
    assert written(url, later) == (1, 1, 1, 1)
    assert (current_effect(url, earlier), current_effect(url, later.inspection_id)) == (
        "INSPECTION_ONLY",
        "INSPECTION_ONLY",
    )
    assert one(url, "SELECT app.invoice_line_is_pet_damage(%s,%s)", case["pet_line"], lease) == (
        True,
    )
    # Every supersede on that Lease is refused, also of the inspection recorded after closure
    # (owner answer to Q-2026-10-08-49, point 1; the known limit of point 4).
    second = inspection(url, lease, uuid4(), supersedes=later.inspection_id)
    with pytest.raises(MoveOutInspectionConflictError) as again:
        inspection_flow().record(
            prop, lease, second, actor=inspection_actor(human, prop), request_id="later-supersede"
        )
    assert refused(again) == ("P5S01", SUPERSEDE_CLOSED)
    assert written(url, second) == (0, 0, 0, 0)
    assert current_effect(url, later.inspection_id) == "INSPECTION_ONLY"
    # An exact repeat of the accepted inspection still replays its response and writes nothing.
    replay = inspection_flow().record(
        prop, lease, later, actor=inspection_actor(human, prop), request_id="later-inspection"
    )
    assert (replay.status_code, replay.body) == (201, result.body)
    assert written(url, later) == (1, 1, 1, 1)


def test_a_supersede_before_closure_is_accepted_and_after_closure_refused(
    migrated_database_url: str,
) -> None:
    """Before the Final Settlement closes, the supersede is accepted as before; after the
    closure an exact repeat of that supersede still replays its saved response and writes
    nothing, and a new supersede, of the superseding inspection, is refused."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, lease = case["prop"], case["human"], case["lease"]
    earlier = inspection_of(url, lease)
    before = inspection(url, lease, uuid4(), supersedes=earlier)
    accepted = inspection_flow().record(
        prop, lease, before, actor=inspection_actor(human, prop), request_id="open-supersede"
    )
    assert written(url, before) == (1, 1, 1, 1)
    assert (current_effect(url, earlier), current_effect(url, before.inspection_id)) == (
        "SUPERSEDED",
        "INSPECTION_ONLY",
    )
    close(url, human, case["settlement"])
    # Review round 1: the exact-repeat replay stays first and writes nothing.
    replay = inspection_flow().record(
        prop, lease, before, actor=inspection_actor(human, prop), request_id="open-supersede"
    )
    assert (replay.status_code, replay.body) == (201, accepted.body)
    assert written(url, before) == (1, 1, 1, 1)
    after = inspection(url, lease, uuid4(), supersedes=before.inspection_id)
    with pytest.raises(MoveOutInspectionConflictError) as failure:
        inspection_flow().record(
            prop, lease, after, actor=inspection_actor(human, prop), request_id="closed-supersede"
        )
    assert refused(failure) == ("P5S01", SUPERSEDE_CLOSED)
    assert written(url, after) == (0, 0, 0, 0)
    assert current_effect(url, before.inspection_id) == "INSPECTION_ONLY"


def test_the_insert_trigger_refuses_a_superseding_row_after_closure(
    migrated_database_url: str,
) -> None:
    """The BEFORE INSERT trigger repeats the refusal: a superseding row inserted directly by the
    table owner is refused outside READ COMMITTED (55000); at READ COMMITTED it passes the
    trigger before closure (and fails only at the deferred completion check, because it has no
    command evidence), and is refused by the trigger after closure (P5S01)."""
    url = migrated_database_url
    case = leaving_case(url)
    human, prop, lease = case["human"], case["prop"], case["lease"]
    earlier = inspection_of(url, lease)
    insert = (
        "INSERT INTO app.move_out_inspections VALUES(%s,%s,%s,%s,%s,'Direct row',"
        "clock_timestamp(),%s,'Approved inspection','Evidence-905','Direct insert',%s)"
    )

    def direct(connection: psycopg.Connection[Any]) -> None:
        version = int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0]))
        connection.execute(insert, (uuid4(), prop, lease, version, today(url), human, earlier))

    # The trigger also refuses a superseding row outside READ COMMITTED (owner answer to
    # Q-2026-10-08-51).
    with pytest.raises(psycopg.Error) as isolated, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        direct(connection)
    assert (isolated.value.sqlstate, isolated.value.diag.message_primary) == (
        "55000",
        OUTSIDE_READ_COMMITTED,
    )
    with pytest.raises(psycopg.Error) as open_settlement, psycopg.connect(url) as connection:
        direct(connection)
        connection.commit()
    assert (open_settlement.value.sqlstate, open_settlement.value.diag.message_primary) == (
        "23514",
        "Inspection command evidence is required",
    )
    close(url, human, case["settlement"])
    with pytest.raises(psycopg.Error) as closed, psycopg.connect(url) as connection:
        direct(connection)
    assert (closed.value.sqlstate, closed.value.diag.message_primary) == (
        "P5S01",
        SUPERSEDE_CLOSED,
    )
    assert current_effect(url, earlier) == "INSPECTION_ONLY"


def test_a_supersede_at_repeatable_read_cannot_miss_a_closure(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap found in review round 1 (owner answer to Q-2026-10-08-51): a REPEATABLE READ
    transaction whose snapshot was taken before the Final Settlement existed still sees no
    Settlement row after the Settlement starts and closes, so the closed-Settlement read alone
    would let its supersede through. The supersede is refused (55000) because it does not run at
    READ COMMITTED, and nothing is written."""
    url = migrated_database_url
    older = psycopg.connect(url)

    def start_after_the_snapshot(prop: UUID, human: UUID, lease: UUID) -> UUID:
        # The snapshot is taken right before leaving_case starts the Settlement, after the
        # Lease, its inspection and the termination exist.
        older.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert older.execute(
            "SELECT count(*) FROM app.final_settlements WHERE lease_id=%s", (lease,)
        ).fetchone() == (0,)
        return start_settlement(prop, human, lease)

    monkeypatch.setattr(final_settlement_draft_tests, "start", start_after_the_snapshot)
    try:
        case = leaving_case(url)
        human, lease = case["human"], case["lease"]
        close(url, human, case["settlement"])
        command = inspection(url, lease, uuid4(), supersedes=inspection_of(url, lease))
        # The older snapshot still sees no Settlement row, closed or not.
        assert older.execute(
            "SELECT count(*) FROM app.final_settlements WHERE lease_id=%s", (lease,)
        ).fetchone() == (0,)
        with pytest.raises(psycopg.Error) as failure:
            record_directly(older, case, command, "repeatable-read-supersede")
    finally:
        older.rollback()
        older.close()
    assert (failure.value.sqlstate, failure.value.diag.message_primary) == (
        "55000",
        OUTSIDE_READ_COMMITTED,
    )
    assert written(url, command) == (0, 0, 0, 0)
    assert one(
        url,
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        case["settlement"],
    ) == (True,)


def test_a_supersede_outside_read_committed_is_refused_also_before_closure(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-08-51: a supersede outside READ COMMITTED is refused (55000)
    before closure too, at REPEATABLE READ and at SERIALIZABLE, with nothing written. An
    inspection that supersedes nothing is not affected, and the same supersede at READ COMMITTED
    is accepted while the Settlement is open."""
    url = migrated_database_url
    case = leaving_case(url)
    lease = case["lease"]
    earlier = inspection_of(url, lease)
    for level in (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
    ):
        command = inspection(url, lease, uuid4(), supersedes=earlier)
        with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
            connection.execute(level)
            record_directly(connection, case, command, "isolated-supersede")
        assert (failure.value.sqlstate, failure.value.diag.message_primary) == (
            "55000",
            OUTSIDE_READ_COMMITTED,
        ), level
        assert written(url, command) == (0, 0, 0, 0), level
    unrelated = inspection(url, lease, uuid4())
    with psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        record_directly(connection, case, unrelated, "isolated-inspection")
    assert written(url, unrelated) == (1, 1, 1, 1)
    accepted = inspection(url, lease, uuid4(), supersedes=earlier)
    with psycopg.connect(url) as connection:
        record_directly(connection, case, accepted, "read-committed-supersede")
    assert written(url, accepted) == (1, 1, 1, 1)
    assert current_effect(url, earlier) == "SUPERSEDED"


def test_a_supersede_waiting_on_the_settlement_confirm_is_refused_once_it_commits(
    migrated_database_url: str,
) -> None:
    """The Settlement confirm (8e-3) locks the Lease row FOR UPDATE; a supersede that starts
    while the confirm runs waits on that lock and, once the confirm commits the closure, reads
    the closed Settlement and is refused (P5S01) with nothing written."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    prop, human, lease = case["prop"], case["human"], case["lease"]
    draft = record(case, normal_plan(case), pet_remainder=STAFF)
    earlier = inspection_of(url, lease)
    command = inspection(url, lease, uuid4(), supersedes=earlier)
    application_name = f"v1056-inspection-closure-{uuid4().hex}"
    inspections = PostgresMoveOutInspectionService(
        runtime_database_url(),
        make_conninfo(financial_database_url(), application_name=application_name),
    )
    with psycopg.connect(url) as holding:
        holding.execute(
            CONFIRM_SQL, (prop, human, UUID(str(draft["draft_id"])), "financial.approve")
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                inspections.record,
                prop,
                lease,
                command,
                actor=inspection_actor(human, prop),
                request_id="supersede-during-closure",
            )
            try:
                assert blocked_on_lease_row(application_name, holding), (
                    "The supersede must wait on the confirm's Lease lock"
                )
            finally:
                holding.commit()
            with pytest.raises(MoveOutInspectionConflictError) as failure:
                future.result(timeout=10)
    assert refused(failure) == ("P5S01", SUPERSEDE_CLOSED)
    assert one(
        url,
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        case["settlement"],
    ) == (True,)
    assert written(url, command) == (0, 0, 0, 0)
    assert current_effect(url, earlier) == "INSPECTION_ONLY"


def test_the_inspection_refusal_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        # The command keeps its financial-role grant only; the trigger function has none.
        assert [
            connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, COMMAND)
            ).fetchone()
            for role in ("prm_financial", "prm_runtime", "prm_bootstrap", "public")
        ] == [(True,), (False,), (False,), (False,)]
        for role in ("prm_financial", "prm_runtime", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, SOURCE)
            ).fetchone() == (False,), role
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261108_104")
    assert revision is not None and revision.down_revision == "20261107_103"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.prosecdef,p.proconfig,p.proacl::text,p.proowner "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("inspection_supersede_after_closure") as temporary:
        alembic_command.upgrade(config, "20261107_103")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261108_104")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {COMMAND, SOURCE}
    for name in (COMMAND, SOURCE):
        # Only the body changed: security, settings, privileges and owner are kept.
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(after_functions[name][0])
        assert "10c-2a-4" in body and "10c-2a-4" not in str(before_functions[name][0]), name
        assert body.count("'P5S01'") == 1, name
        # A supersede runs only at READ COMMITTED, checked before the Settlement read (owner
        # answer to Q-2026-10-08-51).
        assert body.count("'55000'") == 1, name
        assert body.index("current_setting('transaction_isolation')") < body.index(
            "FROM app.final_settlements settlement"
        ), name
        # The refusal reads the Settlement row FOR SHARE, after the Lease row lock.
        lease_lock = body.index("FROM app.leases WHERE id=")
        settlement_lock = body.index("FROM app.final_settlements settlement")
        assert lease_lock < settlement_lock, name
        assert re.search(r"WHERE settlement\.lease_id=(p_lease|NEW\.lease_id) FOR SHARE;", body), (
            name
        )
