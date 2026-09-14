"""Real inspection source, replay, history, concurrency and additive upgrade proof."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_inspection import (
    INSPECTION_READ,
    INSPECTION_RECORD,
    InspectionFinding,
    MoveOutInspectionAuthorizationError,
    MoveOutInspectionConflictError,
    MoveOutInspectionKeyReused,
    MoveOutInspectionNotFoundError,
    MoveOutInspectionResponse,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
    inspection_request_digest,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_notices_migration import source as notice_source
from test_migrations import _temporary_migration_database
from test_termination_deposit_migration import history

NEW_TABLES = {"move_out_inspections", "inspection_damage_findings", "move_out_inspection_commands"}


def flow() -> PostgresMoveOutInspectionService:
    return PostgresMoveOutInspectionService(runtime_database_url(), financial_database_url())


def actor(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(cap, frozenset({str(prop)}))
            for cap in (INSPECTION_READ, INSPECTION_RECORD)
        ),
    )


def source(url: str) -> tuple[UUID, UUID, UUID, RecordMoveOutInspection]:
    human, prop, lease, notice = notice_source(url)
    return (
        human,
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            notice.expected_lease_version,
            notice.notice_date,
            "Recorded inspection condition",
            "Approved inspection",
            "Evidence-001",
            "Record actual inspection",
            (
                InspectionFinding(uuid4(), "Door condition", False),
                InspectionFinding(uuid4(), "Observed pet-related condition", True),
            ),
        ),
    )


def snapshot(url: str) -> dict[str, list[tuple[object, ...]]]:
    with psycopg.connect(url) as connection:
        return history(connection)


def raw_record(
    connection: psycopg.Connection[tuple[object, ...]],
    prop: UUID,
    lease: UUID,
    human: UUID,
    command: RecordMoveOutInspection,
    *,
    intent: dict[str, object] | None = None,
) -> dict[str, object]:
    body = command.intent() if intent is None else intent
    row = connection.execute(
        "SELECT app.move_out_inspection_record(%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            lease,
            human,
            command.idempotency_key,
            inspection_request_digest(prop, lease, body),
            Jsonb(body),
            "direct",
        ),
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return cast(dict[str, object], row[0])


def test_inspection_correction_preserves_original_history_without_physical_or_financial_effects(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    staff = actor(human, prop)
    original = flow().record(prop, lease, request, actor=staff, request_id="original")
    assert flow().record(prop, lease, request, actor=staff, request_id="retry") == original
    correction = replace(
        request,
        idempotency_key=uuid4(),
        inspection_id=uuid4(),
        supersedes_inspection_id=request.inspection_id,
        result_text="Corrected inspection description",
        reason="Correct source evidence",
        findings=(InspectionFinding(uuid4(), "Corrected door description", False),),
    )
    corrected = flow().record(prop, lease, correction, actor=staff, request_id="correction")
    assert flow().record(prop, lease, request, actor=staff, request_id="original-later") == original
    assert corrected.status_code == original.status_code == 201
    old_data = cast(dict[str, object], original.body["data"])
    new_data = cast(dict[str, object], corrected.body["data"])
    assert old_data["current_effect"] == new_data["current_effect"] == "INSPECTION_ONLY"
    assert new_data["supersedes_inspection_id"] == str(request.inspection_id)
    after = snapshot(migrated_database_url)
    assert all(
        after[table] == rows
        for table, rows in before.items()
        if table not in NEW_TABLES | {"audit_events"}
    )
    assert len(after["audit_events"]) == len(before["audit_events"]) + 2
    page = flow().read(prop, lease, actor=staff, limit=1)
    assert page["total"] == 2 and len(cast(list[object], page["items"])) == 1
    first = cast(list[dict[str, object]], page["items"])[0]
    assert first["current_effect"] == "SUPERSEDED"
    assert first["findings"] == old_data["findings"]
    for field in ("records_physical_departure", "financial_completion_assessed", "creates_charge"):
        assert page[field] is False and new_data[field] is False
    next_page = flow().read(prop, lease, actor=staff, limit=1, offset=1)
    assert cast(list[dict[str, object]], next_page["items"])[0]["id"] == str(
        correction.inspection_id
    )
    with pytest.raises(MoveOutInspectionKeyReused):
        flow().record(
            prop, lease, replace(request, reason="Changed"), actor=staff, request_id="changed"
        )
    with pytest.raises(MoveOutInspectionConflictError):
        flow().record(
            prop,
            lease,
            replace(correction, idempotency_key=uuid4(), inspection_id=uuid4(), findings=()),
            actor=staff,
            request_id="second-correction",
        )
    assert snapshot(migrated_database_url) == after


def test_inspection_empty_findings_and_two_commands_in_one_transaction_preserve_exact_responses(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    request = replace(request, findings=())
    correction = replace(
        request,
        idempotency_key=uuid4(),
        inspection_id=uuid4(),
        supersedes_inspection_id=request.inspection_id,
        reason="Correct same transaction evidence",
    )
    with psycopg.connect(financial_database_url()) as connection:
        original = raw_record(connection, prop, lease, human, request)
        corrected = raw_record(connection, prop, lease, human, correction)
    assert (
        cast(dict[str, object], cast(dict[str, object], original["body"])["data"])["findings"] == []
    )
    with psycopg.connect(financial_database_url()) as connection:
        assert raw_record(connection, prop, lease, human, request) == original
        assert raw_record(connection, prop, lease, human, correction) == corrected


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_inspection_retry_and_competing_correction_are_serialized(
    migrated_database_url: str, same_key: bool
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    staff = actor(human, prop)
    if not same_key:
        flow().record(prop, lease, request, actor=staff, request_id="baseline")
        request = replace(
            request,
            idempotency_key=uuid4(),
            inspection_id=uuid4(),
            supersedes_inspection_id=request.inspection_id,
            findings=(),
            reason="Correct baseline",
        )
    barrier = Barrier(2)

    def submit(index: int) -> MoveOutInspectionResponse | MoveOutInspectionConflictError:
        chosen = (
            request
            if same_key or index == 0
            else replace(request, idempotency_key=uuid4(), inspection_id=uuid4())
        )
        barrier.wait(timeout=5)
        try:
            return flow().record(prop, lease, chosen, actor=staff, request_id=f"parallel-{index}")
        except MoveOutInspectionConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    if same_key:
        assert results[0] == results[1]
    else:
        assert sum(isinstance(result, MoveOutInspectionConflictError) for result in results) == 1
    assert flow().read(prop, lease, actor=staff)["total"] == (1 if same_key else 2)


def test_inspection_fresh_actor_property_and_version_checks_preserve_state(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    staff = actor(human, prop)
    with pytest.raises(MoveOutInspectionConflictError):
        flow().record(
            prop,
            lease,
            replace(request, expected_lease_version=request.expected_lease_version + 1),
            actor=staff,
            request_id="stale",
        )
    with pytest.raises(MoveOutInspectionConflictError):
        flow().record(
            prop,
            lease,
            replace(request, inspection_date=request.inspection_date + timedelta(days=1)),
            actor=staff,
            request_id="future",
        )
    wrong = uuid4()
    with pytest.raises(MoveOutInspectionNotFoundError):
        flow().record(wrong, lease, request, actor=actor(human, wrong), request_id="scope")
    assert snapshot(migrated_database_url) == before
    original = flow().record(prop, lease, request, actor=staff, request_id="original")
    assert original.status_code == 201
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    disabled = snapshot(migrated_database_url)
    with pytest.raises(MoveOutInspectionAuthorizationError):
        flow().record(prop, lease, request, actor=staff, request_id="disabled-replay")
    with pytest.raises(MoveOutInspectionAuthorizationError):
        flow().read(prop, lease, actor=staff)
    assert snapshot(migrated_database_url) == disabled


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_lease_version": True},
        {"expected_lease_version": 2147483648},
        {"inspection_date": "2026-02-30"},
        {"inspection_id": "invalid"},
        {"unexpected": "value"},
        {"authorization_reference": None},
        {"reason": "\u2003x"},
        {"findings": None},
        {
            "findings": [
                {"finding_id": str(uuid4()), "description": "Condition", "pet_related": "false"}
            ]
        },
    ],
)
def test_inspection_direct_storage_rejects_invalid_intent_without_side_effects(
    migrated_database_url: str, patch: dict[str, object]
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as error:
            raw_record(connection, prop, lease, human, request, intent=request.intent() | patch)
        assert error.value.sqlstate == "P5M02"
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_inspection_history_and_roles_prohibit_destructive_mutation(
    migrated_database_url: str, table: str, operation: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    flow().record(prop, lease, request, actor=actor(human, prop), request_id="record")
    before = snapshot(migrated_database_url)
    column = "inspection_id" if table == "move_out_inspection_commands" else "id"
    query = sql.SQL(
        "TRUNCATE app.{}"
        if operation == "TRUNCATE"
        else "DELETE FROM app.{}"
        if operation == "DELETE"
        else f"UPDATE app.{{}} SET {column}={column}"
    ).format(sql.Identifier(table))
    for url in (migrated_database_url, runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(query)
    assert snapshot(migrated_database_url) == before


def test_inspection_completed_finding_set_cannot_gain_unrecorded_evidence(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    flow().record(prop, lease, request, actor=actor(human, prop), request_id="record")
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                (
                    "INSERT INTO app.inspection_damage_findings SELECT %s,id,3,%s,fals"
                    "e,completed_at,completed_by FROM app.move_out_inspections WHERE i"
                    "d=%s"
                ),
                (uuid4(), "Unrecorded later finding", request.inspection_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(migrated_database_url) == before


def test_inspection_function_permissions_and_damage_admission_remain_narrow(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conreli"
            "d='app.authorized_nonrecurring_obligations'::regclass AND conname"
            "='authorized_nonrecurring_damage_source_deferred'"
        ).fetchone() == ("CHECK ((category <> 'DAMAGE_CHARGES'::text))",)
        for role, expected in [
            ("prm_runtime", (True, False, False)),
            ("prm_financial", (False, True, False)),
            ("prm_bootstrap", (False, False, False)),
        ]:
            row = connection.execute(
                (
                    "SELECT has_function_privilege(%s,'app.move_out_inspection_read(uu"
                    "id,uuid,uuid,integer,integer)','EXECUTE'),has_function_privilege("
                    "%s,'app.move_out_inspection_record(uuid,uuid,uuid,uuid,text,jsonb"
                    ",text)','EXECUTE'),has_function_privilege(%s,'app.move_out_inspec"
                    "tion_snapshot(uuid)','EXECUTE')"
                ),
                (role, role, role),
            ).fetchone()
            assert row == expected


def test_forward60_preserves_all59_rows_functions_constraints_and_permissions(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert migrated_database_url
    function_query = (
        "SELECT p.oid,pg_get_functiondef(p.oid),p.proacl::text,p.proowner "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE "
        "n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    table_query = (
        "SELECT c.oid,c.relacl::text,c.relowner FROM pg_class c JOIN pg_na"
        "mespace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.rel"
        "kind='r' ORDER BY c.oid"
    )
    constraint_query = (
        "SELECT con.oid,pg_get_constraintdef(con.oid) FROM pg_constraint c"
        "on JOIN pg_namespace n ON n.oid=con.connamespace WHERE n.nspname="
        "'app' ORDER BY con.oid"
    )
    with (
        _temporary_migration_database("inspection") as temporary,
        monkeypatch.context() as environment,
    ):
        name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv("APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=name))
        environment.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=name)
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_59")
        human, prop, lease, request = source(temporary)
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            functions = {row[0]: row[1:] for row in connection.execute(function_query)}
            tables = {row[0]: row[1:] for row in connection.execute(table_query)}
            constraints = {row[0]: row[1:] for row in connection.execute(constraint_query)}
        alembic_command.upgrade(config, "20260915_60")
        with psycopg.connect(temporary) as connection:
            after = history(connection)
            assert all(after[table] == rows for table, rows in before.items())
            assert set(after) - set(before) == NEW_TABLES
            for query, old in (
                (function_query, functions),
                (table_query, tables),
                (constraint_query, constraints),
            ):
                current = {row[0]: row[1:] for row in connection.execute(query)}
                assert all(current[key] == value for key, value in old.items())
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260915_60",
            )
        response = flow().record(
            prop, lease, request, actor=actor(human, prop), request_id="upgraded"
        )
        assert response.status_code == 201
        after_record = snapshot(temporary)
        assert all(
            after_record[table] == rows for table, rows in before.items() if table != "audit_events"
        )
