"""Real PostgreSQL evidence for explicit termination prerequisites."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import (
    LeaseAuthorizationError,
    LeaseCommandConflictError,
    LeaseCommandInvalidError,
    LeaseNotFoundError,
    LeaseStatus,
    LeaseTerminateCommand,
    LeaseVersionConflictError,
    PostgresLeaseService,
    lease_request_digest,
)
from property_rental.lease_enforcement import PostgresLeaseEnforcementService, RecordLeaseWarning
from property_rental.lease_notices import PostgresLeaseNoticeService, RecordLeaseNotice
from property_rental.lease_termination import TerminationBasis, TerminationContext
from test_billing_service_migration import (
    _processed_final_month_source,
    financial_database_url,
    runtime_database_url,
)
from test_billing_service_migration import (
    connection as connection,
)
from test_billing_service_migration import (
    migrated_database_url as migrated_database_url,
)
from test_lease_termination import context_without_notice


def test_new_legacy_entry_termination_requires_explicit_approved_context(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    version = connection.execute("SELECT version FROM app.leases WHERE id=%s", (lease,)).fetchone()
    assert version is not None
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="context"):
        connection.execute(
            "SELECT app.terminate_lease(%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),%s,%s,%s)",
            (
                prop,
                uuid4(),
                "a" * 64,
                uuid4(),
                lease,
                version[0],
                date(2026, 7, 10),
                "BR-LEASE-021",
                "Explicit approved governing context is required for this new command",
                human,
            ),
        )
    connection.rollback()
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )
    assert connection.execute(
        "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.terminate'",
        (lease,),
    ).fetchone() == (0,)


def termination_actor(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(name, frozenset({str(prop)}))
            for name in ("leases.terminate", "leases.warn", "leases.read")
        ),
    )


def termination_command(
    connection: Connection[tuple[object, ...]],
    lease: UUID,
    *,
    context: TerminationContext | None = None,
    governing: str = "BR-LEASE-021",
    actual_date: date = date(2026, 7, 10),
) -> LeaseTerminateCommand:
    row = connection.execute(
        "SELECT version,statement_timestamp() FROM app.leases WHERE id=%s", (lease,)
    ).fetchone()
    assert row is not None and isinstance(row[1], datetime)
    connection.commit()
    return LeaseTerminateCommand(
        uuid4(),
        uuid4(),
        lease,
        int(str(row[0])),
        actual_date,
        row[1],
        governing,
        "Approved actual termination",
        "leases.terminate",
        context=context or context_without_notice(),
    )


def raw_termination_parameters(
    command: LeaseTerminateCommand, prop: UUID, human: UUID, intent: dict[str, object]
) -> tuple[object, ...]:
    return (
        prop,
        command.idempotency_key,
        lease_request_digest("lease.terminate", command),
        command.event_id,
        command.lease_id,
        command.expected_version,
        command.actual_termination_date,
        command.occurred_at,
        command.governing_event_reference,
        command.reason,
        human,
        Jsonb(intent),
    )


CONTEXT_QUERY = "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"


def notice_termination_source(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    row = connection.execute(
        "SELECT timezone('Asia/Phnom_Penh',statement_timestamp())::date"
    ).fetchone()
    assert row is not None and type(row[0]) is date
    return _processed_final_month_source(connection, row[0].replace(day=1), terminate=False)


def record_applicable_notice(
    connection: Connection[tuple[object, ...]],
    human: UUID,
    prop: UUID,
    lease: UUID,
    *,
    supersedes: UUID | None = None,
) -> UUID:
    row = connection.execute(
        "SELECT version,timezone('Asia/Phnom_Penh',statement_timestamp())::date "
        "FROM app.leases WHERE id=%s",
        (lease,),
    ).fetchone()
    assert row is not None and type(row[1]) is date
    notice_date = row[1]
    connection.commit()
    notice = RecordLeaseNotice(
        uuid4(),
        uuid4(),
        int(str(row[0])),
        notice_date,
        notice_date,
        "Approved actual departure notice",
        "Signed Lease section 18",
        "Approved voluntary departure",
        "Signed surrender terms permit completion on the recorded notice date",
        "Signed notice source",
        "Notice delivered to the Customer",
        "Management notice approval",
        "Record the applicable signed notice",
        supersedes_notice_id=supersedes,
    )
    PostgresLeaseNoticeService(runtime_database_url(), financial_database_url()).record(
        prop, lease, notice, actor=termination_actor(human, prop), request_id="termination-notice"
    )
    return notice.notice_id


def record_general_warnings(
    human: UUID, prop: UUID, lease: UUID, *, start: int = 1, warning_date: date = date(2026, 6, 16)
) -> tuple[UUID, ...]:
    flow = PostgresLeaseEnforcementService(runtime_database_url(), financial_database_url())
    ids = []
    for sequence in range(start, start + 3):
        request = RecordLeaseWarning(
            uuid4(),
            sequence,
            date(2026, 6, 15),
            warning_date,
            "Documented signed-Lease violation",
            "Signed Lease section 18",
            "Written warning delivered",
            "Preserve the general warning letter",
        )
        response = flow.record_warning(
            prop,
            lease,
            request,
            actor=termination_actor(human, prop),
            request_id="termination-warning",
        )
        body = response.body["data"]
        assert isinstance(body, dict)
        ids.append(UUID(str(body["id"])))
    return tuple(ids)


def test_explicit_voluntary_context_preserves_physical_and_financial_state(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, occupancy = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    before = connection.execute(
        "SELECT to_jsonb(u),to_jsonb(o) FROM app.leases l JOIN app.units u "
        "ON u.id=l.unit_id JOIN app.occupancies o ON o.lease_id=l.id "
        "WHERE l.id=%s AND o.id=%s",
        (lease, occupancy),
    ).fetchone()
    assert before is not None and isinstance(before[1], dict)
    assert before[1]["move_out_date"] is None
    request = termination_command(connection, lease)
    flow = PostgresLeaseService(runtime_database_url(), prop, human)
    result = flow.terminate(request, actor=termination_actor(human, prop))
    assert result.status is LeaseStatus.TERMINATED and result.actual_termination_date == date(
        2026, 7, 10
    )
    assert result.version == request.expected_version + 1 and result.occupant_count == 1
    assert (
        connection.execute(
            "SELECT to_jsonb(u),to_jsonb(o) FROM app.leases l JOIN app.units u "
            "ON u.id=l.unit_id JOIN app.occupancies o ON o.lease_id=l.id "
            "WHERE l.id=%s AND o.id=%s",
            (lease, occupancy),
        ).fetchone()
        == before
    )
    assert request.context is not None
    row = connection.execute(
        "SELECT context_data,request_digest,actor_id,lease_id FROM "
        "app.lease_termination_contexts WHERE command_event_id=%s",
        (request.event_id,),
    ).fetchone()
    assert row == (
        request.context.intent(),
        lease_request_digest("lease.terminate", request),
        human,
        lease,
    )
    assert connection.execute(
        "SELECT count(*) FROM app.deposits WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT governing_event_reference FROM app.lease_commands WHERE event_id=%s",
        (request.event_id,),
    ).fetchone() == ("BR-LEASE-021",)


def test_termination_context_replay_binds_both_digest_and_actual_database_intent(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    flow = PostgresLeaseService(runtime_database_url(), prop, human)
    actor = termination_actor(human, prop)
    result = flow.terminate(request, actor=actor)
    assert flow.terminate(request, actor=actor) == result
    assert request.context is not None
    with pytest.raises(LeaseCommandConflictError):
        flow.terminate(
            replace(request, context=replace(request.context, evidence_reference="Changed intent")),
            actor=actor,
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            CONTEXT_QUERY,
            raw_termination_parameters(
                request,
                prop,
                human,
                request.context.intent()
                | {"evidence_reference": "Changed body with original digest"},
            ),
        )
    connection.rollback()
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (1,)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(
            "UPDATE app.lease_termination_contexts SET reason='Changed history' "
            "WHERE command_event_id=%s",
            (request.event_id,),
        )
    connection.rollback()


def test_current_notice_and_documented_period_support_explicit_termination(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, _ = notice_termination_source(connection)
    notice_id = record_applicable_notice(connection, human, prop, lease)
    date_row = connection.execute(
        "SELECT notice_date FROM app.termination_notices WHERE id=%s", (notice_id,)
    ).fetchone()
    assert date_row is not None and type(date_row[0]) is date
    actual_date = date_row[0]
    context = context_without_notice(
        notice_required=True,
        notice_id=notice_id,
        notice_period_ends_on=actual_date,
        notice_exception_reason=None,
    )
    request = termination_command(connection, lease, context=context, actual_date=actual_date)
    flow = PostgresLeaseService(runtime_database_url(), prop, human)
    result = flow.terminate(request, actor=termination_actor(human, prop))
    assert result.status is LeaseStatus.TERMINATED
    assert connection.execute(
        "SELECT notice_id FROM app.lease_termination_contexts WHERE command_event_id=%s",
        (request.event_id,),
    ).fetchone() == (notice_id,)
    assert flow.terminate(request, actor=termination_actor(human, prop)) == result


@pytest.mark.parametrize(
    "condition",
    (
        "superseded",
        "wrong_lease",
        "period_before_notice",
        "period_after_actual",
        "wrong_provision",
        "wrong_grounds",
    ),
)
def test_termination_rechecks_current_notice_relationship_and_period(
    connection: Connection[tuple[object, ...]],
    condition: str,
) -> None:
    human, prop, _, lease, _ = notice_termination_source(connection)
    notice_lease = lease
    if condition == "wrong_lease":
        _, _, _, notice_lease, _ = notice_termination_source(connection)
    notice_id = record_applicable_notice(connection, human, prop, notice_lease)
    date_row = connection.execute(
        "SELECT notice_date FROM app.termination_notices WHERE id=%s", (notice_id,)
    ).fetchone()
    assert date_row is not None and type(date_row[0]) is date
    actual_date = date_row[0]
    if condition == "superseded":
        record_applicable_notice(connection, human, prop, lease, supersedes=notice_id)
    context = context_without_notice(
        notice_required=True,
        notice_id=notice_id,
        notice_period_ends_on=actual_date,
        notice_exception_reason=None,
    )
    request = termination_command(connection, lease, context=context, actual_date=actual_date)
    intent = context.intent()
    if condition == "period_before_notice":
        intent["notice_period_ends_on"] = (actual_date - timedelta(days=1)).isoformat()
    if condition == "period_after_actual":
        intent["notice_period_ends_on"] = (actual_date + timedelta(days=1)).isoformat()
    if condition == "wrong_provision":
        intent["signed_lease_provision"] = "Different signed clause"
    if condition == "wrong_grounds":
        intent["approved_grounds"] = "Different approved grounds"
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        connection.execute(CONTEXT_QUERY, raw_termination_parameters(request, prop, human, intent))
    connection.rollback()
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)


def test_violation_termination_requires_three_real_general_warning_sources(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    warnings = record_general_warnings(human, prop, lease)
    context = context_without_notice(
        basis=TerminationBasis.CUSTOMER_VIOLATION, warning_ids=warnings
    )
    request = termination_command(connection, lease, context=context, governing="BR-LEASE-025")
    result = PostgresLeaseService(runtime_database_url(), prop, human).terminate(
        request, actor=termination_actor(human, prop)
    )
    assert result.status is LeaseStatus.TERMINATED
    assert {
        row[0]
        for row in connection.execute(
            "SELECT warning_id FROM app.lease_termination_warning_sources WHERE "
            "command_event_id=%s",
            (request.event_id,),
        )
    } == set(warnings)


@pytest.mark.parametrize(
    "condition", ("wrong_lease", "after_actual_date", "after_occurrence", "missing_source")
)
def test_termination_rejects_unrelated_or_late_general_warning_sources(
    connection: Connection[tuple[object, ...]],
    condition: str,
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    early = termination_command(connection, lease).occurred_at
    warning_lease = lease
    if condition == "wrong_lease":
        _, _, _, warning_lease, _ = _processed_final_month_source(
            connection, date(2026, 7, 1), terminate=False
        )
    warnings = record_general_warnings(
        human,
        prop,
        warning_lease,
        warning_date=date(2026, 7, 11) if condition == "after_actual_date" else date(2026, 6, 16),
    )
    if condition == "missing_source":
        warnings = (uuid4(), *warnings[1:])
    context = context_without_notice(
        basis=TerminationBasis.CUSTOMER_VIOLATION, warning_ids=warnings
    )
    request = termination_command(connection, lease, context=context, governing="BR-LEASE-025")
    if condition == "after_occurrence":
        request = replace(request, occurred_at=early)
    with pytest.raises(LeaseCommandInvalidError):
        PostgresLeaseService(runtime_database_url(), prop, human).terminate(
            request, actor=termination_actor(human, prop)
        )
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_warning_sources source "
        "JOIN app.lease_termination_contexts context ON "
        "context.command_event_id=source.command_event_id WHERE "
        "context.lease_id=%s",
        (lease,),
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    "changes",
    (
        {"signed_lease_provision": "\u2003"},
        {"evidence_reference": " copied "},
        {"management_authorization_reference": None},
        {"extra_field": "unsupported"},
        {"notice_required": 1},
        {"notice_exception_reason": None},
        {
            "notice_required": True,
            "notice_id": str(UUID(int=0)),
            "notice_period_ends_on": "2026-07-09",
            "notice_exception_reason": None,
        },
        {
            "notice_required": True,
            "notice_id": str(UUID(int=4)),
            "notice_period_ends_on": "2026-02-30",
            "notice_exception_reason": None,
        },
        {"basis": "CUSTOMER_VIOLATION", "warning_ids": []},
        {"basis": "CUSTOMER_VIOLATION", "warning_ids": [str(UUID(int=4))] * 3},
        {"basis": "SIGNED_LEASE_OTHER"},
    ),
)
def test_database_termination_context_rejects_malformed_or_conflicting_intent(
    connection: Connection[tuple[object, ...]],
    changes: dict[str, object],
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    assert request.context is not None
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        connection.execute(
            CONTEXT_QUERY,
            raw_termination_parameters(request, prop, human, request.context.intent() | changes),
        )
    connection.rollback()
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )


@pytest.mark.parametrize("same_key", (True, False))
def test_concurrent_termination_commands_preserve_one_exact_business_event(
    connection: Connection[tuple[object, ...]],
    same_key: bool,
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    second = request if same_key else replace(request, idempotency_key=uuid4(), event_id=uuid4())
    flow = PostgresLeaseService(runtime_database_url(), prop, human)
    actor = termination_actor(human, prop)

    def execute(value: LeaseTerminateCommand) -> object:
        try:
            return flow.terminate(value, actor=actor)
        except LeaseVersionConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=10)
            for future in [pool.submit(execute, request), pool.submit(execute, second)]
        ]
    if same_key:
        assert results[0] == results[1]
    else:
        assert sum(isinstance(value, LeaseVersionConflictError) for value in results) == 1
    assert connection.execute(
        "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.terminate'",
        (lease,),
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (1,)


@pytest.mark.parametrize("condition", ("capability", "actor", "property", "disabled"))
def test_explicit_termination_preserves_fresh_actor_property_and_capability_checks(
    connection: Connection[tuple[object, ...]],
    condition: str,
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    actor = termination_actor(human, prop)
    service_prop = prop
    expected: type[Exception] = LeaseAuthorizationError
    if condition == "capability":
        actor = AuthenticatedActor(str(human), frozenset())
    if condition == "actor":
        actor = termination_actor(uuid4(), prop)
    if condition == "property":
        service_prop = uuid4()
        actor = termination_actor(human, service_prop)
        expected = LeaseNotFoundError
    if condition == "disabled":
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
        connection.commit()
    with pytest.raises(expected):
        PostgresLeaseService(runtime_database_url(), service_prop, human).terminate(
            request, actor=actor
        )
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )


def test_invalid_actual_date_rolls_back_context_and_termination_together(
    connection: Connection[tuple[object, ...]],
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    row = connection.execute(
        "SELECT timezone('Asia/Phnom_Penh',statement_timestamp())::date+1"
    ).fetchone()
    assert row is not None and type(row[0]) is date
    connection.commit()
    with pytest.raises(LeaseCommandInvalidError):
        PostgresLeaseService(runtime_database_url(), prop, human).terminate(
            replace(request, actual_termination_date=row[0]), actor=termination_actor(human, prop)
        )
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )


@pytest.mark.parametrize("end_day", (9, 10))
def test_voluntary_early_basis_requires_actual_date_before_original_end_date(
    connection: Connection[tuple[object, ...]],
    end_day: int,
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False, end_day=end_day
    )
    request = termination_command(connection, lease)
    with pytest.raises(LeaseCommandInvalidError):
        PostgresLeaseService(runtime_database_url(), prop, human).terminate(
            request, actor=termination_actor(human, prop)
        )


def test_runtime_can_only_use_the_authorized_termination_function(
    connection: Connection[tuple[object, ...]],
) -> None:
    assert connection.execute(
        "SELECT has_function_privilege('prm_runtime','app.terminate_lease_with_"
        "context(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uu"
        "id,jsonb)','EXECUTE')"
    ).fetchone() == (True,)
    for table in ("lease_termination_contexts", "lease_termination_warning_sources"):
        assert connection.execute(
            "SELECT has_table_privilege('prm_runtime',%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
            ("app." + table,),
        ).fetchone() == (False,)
    assert connection.execute(
        "SELECT has_function_privilege('prm_runtime','app.require_lease_termina"
        "tion_context(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,te"
        "xt,uuid)','EXECUTE')"
    ).fetchone() == (False,)


def test_termination_upgrade_preserves_all_prior_functions_history_and_exact_legacy_replay(
    migrated_database_url: str,
) -> None:
    from pathlib import Path

    from alembic import command as alembic_command
    from alembic.config import Config
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from test_migrations import _temporary_migration_database

    assert migrated_database_url
    functions_query = (
        "SELECT p.oid,p.proname,pg_catalog.pg_get_functiondef(p.oid),p.proacl::text,"
        "p.proowner,p.prosecdef,p.provolatile,p.proisstrict,p.proparallel,p.proconfig "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    with _temporary_migration_database("termination_upgrade") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_53")
        with psycopg.connect(temporary) as setup:
            human, prop, _, lease, _ = _processed_final_month_source(
                setup, date(2026, 7, 1), terminate=False
            )
            other_human, other_prop, _, other_lease, _ = _processed_final_month_source(
                setup, date(2026, 7, 1), terminate=False
            )
            legacy_command = replace(termination_command(setup, lease), context=None)
        runtime_url = make_conninfo(
            runtime_database_url(), dbname=conninfo_to_dict(temporary)["dbname"]
        )
        flow = PostgresLeaseService(runtime_url, prop, human)
        actor = termination_actor(human, prop)
        legacy_result = flow.terminate(legacy_command, actor=actor)
        with psycopg.connect(temporary) as check:
            functions_before = {row[0]: row[1:] for row in check.execute(functions_query)}
            old_oid = check.execute(
                "SELECT 'app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,"
                "timestamptz,text,text,uuid)'::regprocedure::oid"
            ).fetchone()
            assert old_oid is not None
            tables = [
                str(row[0])
                for row in check.execute(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname='app' ORDER BY tablename"
                )
            ]
            history = {
                table: check.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text").format(
                        sql.Identifier(table)
                    )
                ).fetchall()
                for table in tables
            }
        alembic_command.upgrade(config, "head")
        with psycopg.connect(temporary) as check:
            after = {row[0]: row[1:] for row in check.execute(functions_query)}
            assert functions_before.keys() <= after.keys()
            assert {oid for oid in functions_before if functions_before[oid] != after[oid]} == {
                old_oid[0]
            }
            # Function name and every privilege/security attribute retain their identity.
            assert functions_before[old_oid[0]][0] == after[old_oid[0]][0]
            assert functions_before[old_oid[0]][2:] == after[old_oid[0]][2:]
            assert {after[oid][0] for oid in after.keys() - functions_before.keys()} == {
                "lease_termination_context_shape_valid",
                "require_lease_termination_context",
                "terminate_lease_with_context",
            }
            for table in tables:
                assert (
                    check.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text"
                        ).format(sql.Identifier(table))
                    ).fetchall()
                    == history[table]
                )
            for table in ("lease_termination_contexts", "lease_termination_warning_sources"):
                assert check.execute(
                    sql.SQL("SELECT count(*) FROM app.{}").format(sql.Identifier(table))
                ).fetchone() == (0,)
        assert flow.terminate(legacy_command, actor=actor) == legacy_result
        with psycopg.connect(temporary) as check:
            new_command = termination_command(check, other_lease)
        other_flow = PostgresLeaseService(runtime_url, other_prop, other_human)
        other_actor = termination_actor(other_human, other_prop)
        with pytest.raises(LeaseCommandInvalidError) as missing_context:
            other_flow.terminate(replace(new_command, context=None), actor=other_actor)
        assert isinstance(missing_context.value.__cause__, psycopg.errors.InvalidParameterValue)
        assert "context" in str(missing_context.value.__cause__)
        with psycopg.connect(temporary) as check:
            for table in tables:
                assert (
                    check.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text"
                        ).format(sql.Identifier(table))
                    ).fetchall()
                    == history[table]
                )
        new_result = other_flow.terminate(new_command, actor=other_actor)
        assert new_result.status is LeaseStatus.TERMINATED
        assert other_flow.terminate(new_command, actor=other_actor) == new_result
        assert flow.terminate(legacy_command, actor=actor) == legacy_result
        with psycopg.connect(temporary) as check:
            assert check.execute(
                "SELECT command_event_id FROM app.lease_termination_contexts"
            ).fetchall() == [(new_command.event_id,)]
            assert (
                check.execute(
                    "SELECT result_snapshot FROM app.lease_commands WHERE event_id=%s",
                    (legacy_command.event_id,),
                ).fetchone()
                is not None
            )


@pytest.mark.parametrize("immediate", (False, True))
def test_termination_context_wrapper_is_atomic_under_each_constraint_mode(
    connection: Connection[tuple[object, ...]],
    immediate: bool,
) -> None:
    human, prop, _, lease, _ = _processed_final_month_source(
        connection, date(2026, 7, 1), terminate=False
    )
    request = termination_command(connection, lease)
    assert request.context is not None
    connection.execute(
        "SET CONSTRAINTS ALL IMMEDIATE" if immediate else "SET CONSTRAINTS ALL DEFERRED"
    )
    row = connection.execute(
        CONTEXT_QUERY, raw_termination_parameters(request, prop, human, request.context.intent())
    ).fetchone()
    assert row is not None and isinstance(row[0], dict) and row[0]["status"] == "TERMINATED"
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts context JOIN app.lease_commands "
        "command ON command.event_id=context.command_event_id WHERE context.lease_id=%s",
        (lease,),
    ).fetchone() == (1,)
    connection.rollback()
    assert connection.execute("SELECT status FROM app.leases WHERE id=%s", (lease,)).fetchone() == (
        "SIGNED",
    )
    assert connection.execute(
        "SELECT count(*) FROM app.lease_termination_contexts WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.terminate'",
        (lease,),
    ).fetchone() == (0,)
