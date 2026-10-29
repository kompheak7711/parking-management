"""Synthetic PostgreSQL notice evidence, preservation and transactional boundaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
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

from property_rental.billing import initial_billing_period, recurring_billing_period
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_notices import (
    NOTICE_READ,
    NOTICE_RECORD,
    LeaseNoticeAuthorizationError,
    LeaseNoticeConflictError,
    LeaseNoticeKeyReused,
    LeaseNoticeNotFoundError,
    LeaseNoticeUnavailableError,
    PostgresLeaseNoticeService,
    RecordLeaseNotice,
)
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
    setup_signed_lease,
)
from test_migrations import _temporary_migration_database
from test_reservation_migration import migrated_database_url  # noqa: F401


def service() -> PostgresLeaseNoticeService:
    return PostgresLeaseNoticeService(runtime_database_url(), financial_database_url())


def staff(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(cap, frozenset({str(prop)})) for cap in (NOTICE_READ, NOTICE_RECORD)
        ),
    )


def notice_fixture_dates(business_date: date) -> tuple[date, date, date]:
    """Dates for the synthetic baseline; calendar regression checks their coverage."""
    recurring_start = (business_date.replace(day=1) - timedelta(days=40)).replace(day=1)
    lease_start = (recurring_start - timedelta(days=1)).replace(day=1)
    return (
        lease_start,
        recurring_start,
        business_date.replace(year=business_date.year + 1, month=12, day=31),
    )


def source(url: str) -> tuple[UUID, UUID, UUID, RecordLeaseNotice]:
    with psycopg.connect(url) as connection:
        today_row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
        assert today_row is not None and isinstance(today_row[0], date)
        today = today_row[0]
        lease_start, period_start, lease_end = notice_fixture_dates(today)
        human, prop, customer, lease = setup_signed_lease(
            connection,
            start_date=lease_start,
            end_date=lease_end,
        )
        create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=period_start,
        )
        row = connection.execute("SELECT version FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
    return (
        human,
        prop,
        lease,
        RecordLeaseNotice(
            uuid4(),
            uuid4(),
            int(str(row[0])),
            today,
            today + timedelta(days=30),
            "Approved notice content",
            "Signed Lease clause 8",
            "Approved documented grounds",
            "Notice terms in signed clause 8",
            "Signed document reference",
            "Delivery record",
            "Management approval reference",
            "Record approved notice",
        ),
    )


# Migrations 227 (Unit setup) and 251 (V1-061 default Rent) add Unit columns; every other value
# must stay as it was.
UNIT_SETUP_COLUMNS = (
    "ARRAY['floor_item_id','size_square_metres','bedrooms','bathrooms',"
    "'view_item_id','kitchen_item_id','notes',"
    "'default_monthly_rent_usd_cents']"
)


def business_snapshot(url: str, lease: UUID) -> list[tuple[object, ...]]:
    # DL-064: migration 64 added the Due Date override columns; an upgrade adds them as
    # null, so they are left out of the before/after Invoice comparison. V1-058 migration 227
    # adds the Unit setup columns the same way (the Floor item is linked from the Floor text).
    with psycopg.connect(url) as connection:
        return connection.execute(
            f"SELECT to_jsonb(l),to_jsonb(u)-{UNIT_SETUP_COLUMNS},to_jsonb(o),to_jsonb(i)-ARRAY["
            "'due_date_override_reason','due_date_set_by','due_date_set_at','draft_reference'],"
            "to_jsonb(il) "
            "FROM app.leases l JOIN app.units u ON u.id=l.unit_id "
            "LEFT JOIN app.occupancies o ON o.lease_id=l.id "
            "LEFT JOIN app.invoices i ON i.lease_id=l.id "
            "LEFT JOIN app.invoice_lines il ON il.invoice_id=i.id "
            "WHERE l.id=%s ORDER BY o.id,i.id,il.id",
            (lease,),
        ).fetchall()


def test_notice_replay_correction_and_paging_preserve_tenancy_financial_sources(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = business_snapshot(migrated_database_url, lease)
    flow, actor = service(), staff(human, prop)
    original = flow.record(prop, lease, request, actor=actor, request_id="notice")
    assert flow.record(prop, lease, request, actor=actor, request_id="retry") == original
    with pytest.raises(LeaseNoticeKeyReused):
        flow.record(
            prop, lease, replace(request, reason="Changed"), actor=actor, request_id="changed"
        )
    correction = replace(
        request,
        idempotency_key=uuid4(),
        notice_id=uuid4(),
        supersedes_notice_id=request.notice_id,
        reason="Correct delivery evidence",
        communication_record="Corrected delivery reference",
    )
    corrected = flow.record(prop, lease, correction, actor=actor, request_id="correct")
    assert flow.record(prop, lease, request, actor=actor, request_id="original-replay") == original
    assert cast(dict[str, object], original.body["data"])["current_effect"] == "NOTICE_ONLY"
    assert cast(dict[str, object], corrected.body["data"])["changes_lease_status"] is False
    listing = flow.read(prop, lease, actor=actor)
    assert listing["total"] == 2
    items = cast(list[dict[str, object]], listing["items"])
    assert {str(item["id"]): item["current_effect"] for item in items} == {
        str(request.notice_id): "SUPERSEDED",
        str(correction.notice_id): "NOTICE_ONLY",
    }
    assert flow.read(prop, lease, actor=actor, limit=1, offset=1)["items"] == [items[1]]
    with pytest.raises(LeaseNoticeConflictError):
        flow.record(
            prop,
            lease,
            replace(correction, notice_id=uuid4(), idempotency_key=uuid4()),
            actor=actor,
            request_id="stale-correction",
        )
    assert business_snapshot(migrated_database_url, lease) == before
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE lease_id=%s AND action='lease"
            ".notice.record'",
            (lease,),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM app.lease_notice_commands WHERE lease_id=%s", (lease,)
        ).fetchone() == (2,)


def test_notice_checks_fresh_actor_property_dates_and_version_before_new_work(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    actor, flow = staff(human, prop), service()
    for bad in (
        replace(request, expected_lease_version=request.expected_lease_version + 1),
        replace(request, notice_date=request.notice_date + timedelta(days=1)),
        replace(request, notice_date=request.notice_date - timedelta(days=1)),
    ):
        with pytest.raises(LeaseNoticeConflictError):
            flow.record(prop, lease, bad, actor=actor, request_id="invalid-source")
    with pytest.raises(LeaseNoticeNotFoundError):
        flow.record(prop, uuid4(), request, actor=actor, request_id="missing")
    other_prop = uuid4()
    with pytest.raises(LeaseNoticeNotFoundError):
        flow.record(other_prop, lease, request, actor=staff(human, other_prop), request_id="scope")
    original = flow.record(prop, lease, request, actor=actor, request_id="original")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    try:
        with pytest.raises(LeaseNoticeAuthorizationError):
            flow.read(prop, lease, actor=actor)
        with pytest.raises(LeaseNoticeAuthorizationError):
            flow.record(prop, lease, request, actor=actor, request_id="disabled-replay")
    finally:
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.user_accounts SET lifecycle_state='active' WHERE actor_id=%s", (human,)
            )
    assert flow.record(prop, lease, request, actor=actor, request_id="recovered") == original


def test_cross_lease_correction_is_hidden_and_changed_lease_version_does_not_break_exact_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    actor = staff(human, prop)
    original = service().record(prop, lease, request, actor=actor, request_id="original")
    other_human, other_prop, other_lease, other = source(migrated_database_url)
    with pytest.raises(LeaseNoticeNotFoundError):
        service().record(
            other_prop,
            other_lease,
            replace(other, supersedes_notice_id=request.notice_id),
            actor=staff(other_human, other_prop),
            request_id="cross-lease",
        )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.leases SET version=version+1,updated_at=clock_timestamp(),upda"
            "ted_by=%s WHERE id=%s",
            (human, lease),
        )
    assert (
        service().record(prop, lease, request, actor=actor, request_id="later-version") == original
    )
    with pytest.raises(LeaseNoticeConflictError):
        service().record(
            prop,
            lease,
            replace(request, idempotency_key=uuid4(), notice_id=uuid4()),
            actor=actor,
            request_id="stale-version",
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_replay_and_correction_have_one_permanent_result(
    migrated_database_url: str,  # noqa: F811
    same_key: bool,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    actor = staff(human, prop)
    if not same_key:
        service().record(prop, lease, request, actor=actor, request_id="original")
        request = replace(
            request,
            idempotency_key=uuid4(),
            notice_id=uuid4(),
            supersedes_notice_id=request.notice_id,
        )
    barrier = Barrier(2)

    def submit(index: int) -> object:
        chosen = (
            request
            if same_key or index == 0
            else replace(request, idempotency_key=uuid4(), notice_id=uuid4())
        )
        barrier.wait(timeout=5)
        try:
            return service().record(
                prop, lease, chosen, actor=actor, request_id=f"concurrent-{index}"
            )
        except LeaseNoticeConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    if same_key:
        assert results[0] == results[1]
    else:
        assert sum(isinstance(item, LeaseNoticeConflictError) for item in results) == 1
    assert service().read(prop, lease, actor=actor)["total"] == (1 if same_key else 2)


@pytest.mark.parametrize(
    "table", ["termination_notices", "lease_notice_contexts", "lease_notice_commands"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_notice_history_is_append_only_and_application_roles_cannot_write_tables(
    migrated_database_url: str,  # noqa: F811
    table: str,
    operation: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    service().record(prop, lease, request, actor=staff(human, prop), request_id="notice")
    column = "id" if table == "termination_notices" else "notice_id"
    query = sql.SQL(
        "TRUNCATE app.{}"
        if operation == "TRUNCATE"
        else "DELETE FROM app.{}"
        if operation == "DELETE"
        else f"UPDATE app.{{}} SET {column}={column}"
    ).format(sql.Identifier(table))
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(query)
    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(query)


def test_only_narrow_notice_entry_points_are_granted(migrated_database_url: str) -> None:  # noqa: F811
    assert migrated_database_url
    for url, expected in (
        (runtime_database_url(), (True, False, False, False)),
        (financial_database_url(), (False, True, False, False)),
    ):
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT has_function_privilege(current_user,'app.lease_notice_read"
                    "(uuid,uuid,uuid,integer,integer)','EXECUTE'),"
                    "has_function_privilege(current_user,'app.lease_notice_record(uuid"
                    ",uuid,uuid,uuid,text,jsonb,text)','EXECUTE'),"
                    "has_function_privilege(current_user,'app.lease_notice_snapshot(uu"
                    "id)','EXECUTE'),"
                    "has_function_privilege(current_user,'app.lease_notice_text_valid"
                    "(text,integer)','EXECUTE')"
                ).fetchone()
                == expected
            )


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_lease_version": True},
        {"expected_lease_version": 2147483648},
        {"approved_grounds": ""},
        {"notice_date": "2026-02-30"},
        {"notice_id": "invalid"},
        {"unexpected": "value"},
        {"notice_period_terms": None},
    ],
)
def test_database_entry_point_rejects_invalid_notice_evidence_atomically(
    migrated_database_url: str,  # noqa: F811
    patch: dict[str, object],
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as error:
            connection.execute(
                "SELECT app.lease_notice_record(%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    lease,
                    human,
                    request.idempotency_key,
                    "a" * 64,
                    Jsonb(request.intent() | patch),
                    "invalid",
                ),
            )
        assert error.value.sqlstate == "P5502"
    assert service().read(prop, lease, actor=staff(human, prop))["total"] == 0


def test_notice_audit_failure_rolls_back_all_rows_and_same_command_recovers(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "CREATE FUNCTION app.test_notice_audit_failure() RETURNS trigger LANGUAGE "
            "plpgsql AS $$ BEGIN IF NEW.action='lease.notice.record' THEN RAISE EXCEPT"
            "ION 'Synthetic audit failure'; END IF; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER test_notice_audit_failure BEFORE INSERT ON app.audit_event"
            "s FOR EACH ROW EXECUTE FUNCTION app.test_notice_audit_failure()"
        )
    try:
        with pytest.raises(LeaseNoticeUnavailableError):
            service().record(
                prop, lease, request, actor=staff(human, prop), request_id="audit-failure"
            )
        with psycopg.connect(migrated_database_url) as connection:
            for table in ("termination_notices", "lease_notice_contexts", "lease_notice_commands"):
                column = "id" if table == "termination_notices" else "notice_id"
                assert connection.execute(
                    sql.SQL(f"SELECT count(*) FROM app.{{}} WHERE {column}=%s").format(
                        sql.Identifier(table)
                    ),
                    (request.notice_id,),
                ).fetchone() == (0,)
    finally:
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute("DROP TRIGGER test_notice_audit_failure ON app.audit_events")
            connection.execute("DROP FUNCTION app.test_notice_audit_failure()")
    result = service().record(prop, lease, request, actor=staff(human, prop), request_id="recover")
    assert (
        service().record(prop, lease, request, actor=staff(human, prop), request_id="replay")
        == result
    )


def test_upgrade_preserves_legacy_notice_and_allows_append_only_correction(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("lease_notice_upgrade") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260910_51")
        human, prop, lease, request = source(temporary)
        legacy = uuid4()
        with psycopg.connect(temporary) as connection:
            connection.execute(
                "INSERT INTO app.termination_notices VALUES(%s,%s,%s,NULL,'Historical "
                "notice','Original signed terms',clock_timestamp(),%s)",
                (legacy, lease, request.notice_date, human),
            )
            before = connection.execute(
                "SELECT to_jsonb(n) FROM app.termination_notices n WHERE id=%s", (legacy,)
            ).fetchone()
        business_before = business_snapshot(temporary, lease)
        alembic_command.upgrade(config, "head")
        database = conninfo_to_dict(temporary)["dbname"]
        flow = PostgresLeaseNoticeService(
            make_conninfo(runtime_database_url(), dbname=database),
            make_conninfo(financial_database_url(), dbname=database),
        )
        actor = staff(human, prop)
        items = cast(list[dict[str, object]], flow.read(prop, lease, actor=actor)["items"])
        assert (
            items[0]["context"] is None and items[0]["current_effect"] == "HISTORICAL_NOTICE_ONLY"
        )
        flow.record(
            prop,
            lease,
            replace(
                request,
                supersedes_notice_id=legacy,
                reason="Document correction to legacy evidence",
            ),
            actor=actor,
            request_id="legacy-correction",
        )
        with psycopg.connect(temporary) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(n) FROM app.termination_notices n WHERE id=%s", (legacy,)
                ).fetchone()
                == before
            )
        assert business_snapshot(temporary, lease) == business_before
        with pytest.raises(RuntimeError, match="forward-only"):
            alembic_command.downgrade(config, "20260910_51")


PYTHON_WHITESPACE = tuple(chr(point) for point in range(0x110000) if chr(point).isspace())
NOTICE_TEXT_FIELDS = (
    "notice_text",
    "governing_lease_provision",
    "approved_grounds",
    "notice_period_terms",
    "evidence_reference",
    "communication_record",
    "authorization_reference",
    "reason",
)


@pytest.mark.parametrize(
    "business_date",
    [
        date(year, month, day)
        for year in (2026, 2027, 2028)
        for month in range(1, 13)
        for day in (1, 13, 28)
    ],
)
def test_notice_fixture_dates_preserve_valid_recurring_coverage(business_date: date) -> None:
    lease_start, period_start, lease_end = notice_fixture_dates(business_date)
    _, initial_end, _ = initial_billing_period(lease_start)
    recurring_start, recurring_end, _, _ = recurring_billing_period(period_start)
    assert lease_start <= recurring_start <= recurring_end <= lease_end
    assert recurring_start > initial_end
    assert recurring_end < business_date < lease_end


@pytest.mark.parametrize("field", NOTICE_TEXT_FIELDS)
def test_notice_database_rejects_blank_and_edge_whitespace_atomically(
    migrated_database_url: str,  # noqa: F811
    field: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        for whitespace in PYTHON_WHITESPACE:
            for value in (whitespace, whitespace + "Approved", "Approved" + whitespace):
                assert value != value.strip() or not value.strip()
                with pytest.raises(psycopg.Error) as error:
                    with connection.transaction():
                        connection.execute(
                            "SELECT app.lease_notice_record(%s,%s,%s,%s,%s,%s,%s)",
                            (
                                prop,
                                lease,
                                human,
                                request.idempotency_key,
                                "a" * 64,
                                Jsonb(request.intent() | {field: value}),
                                "invalid-whitespace",
                            ),
                        )
                assert error.value.sqlstate == "P5502"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT (SELECT count(*) FROM app.termination_notices WHERE id=%s),"
            "(SELECT count(*) FROM app.lease_notice_contexts WHERE notice_id=%s),"
            "(SELECT count(*) FROM app.lease_notice_commands WHERE notice_id=%s),"
            "(SELECT count(*) FROM app.audit_events WHERE lease_id=%s "
            "AND action='lease.notice.record')",
            (request.notice_id, request.notice_id, request.notice_id, lease),
        ).fetchone() == (0, 0, 0, 0)


def test_notice_database_validator_matches_python_whitespace_contract(
    migrated_database_url: str,  # noqa: F811
) -> None:
    values = ["Approved", "", "x" * 5001]
    for whitespace in PYTHON_WHITESPACE:
        values.extend(
            (
                whitespace,
                whitespace + "Approved",
                "Approved" + whitespace,
                "Approved" + whitespace + "evidence",
            )
        )
    values.extend(("Approved\u200bevidence", "Approved\u200bevidence\u200b"))
    with psycopg.connect(migrated_database_url) as connection:
        for value in values:
            expected = bool(value) and value == value.strip() and len(value) <= 5000
            assert connection.execute(
                "SELECT app.lease_notice_text_valid(%s,5000)", (value,)
            ).fetchone() == (expected,)
        assert connection.execute(
            "SELECT app.lease_notice_text_valid(NULL,5000),"
            "app.lease_notice_text_valid('Approved',NULL),"
            "app.lease_notice_text_valid('Approved',0)"
        ).fetchone() == (False, False, False)


def test_notice_internal_whitespace_is_preserved_in_evidence_and_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    text = "Approved\tcontent\nwith\u3000internal formatting"
    request = replace(
        request,
        notice_text=text,
        governing_lease_provision=text,
        approved_grounds=text,
        notice_period_terms=text,
        evidence_reference=text,
        communication_record=text,
        authorization_reference=text,
        reason=text,
    )
    flow, actor = service(), staff(human, prop)
    response = flow.record(prop, lease, request, actor=actor, request_id="formatted")
    assert flow.record(prop, lease, request, actor=actor, request_id="retry") == response
    item = cast(dict[str, object], response.body["data"])
    context = cast(dict[str, object], item["context"])
    assert item["notice_text"] == item["governing_lease_provision"] == text
    assert all(context[field] == text for field in NOTICE_TEXT_FIELDS[2:])


@pytest.mark.parametrize("field", NOTICE_TEXT_FIELDS[2:])
def test_notice_context_constraints_reject_blank_or_edge_whitespace(
    migrated_database_url: str,  # noqa: F811
    field: str,
) -> None:
    human, _, lease, request = source(migrated_database_url)
    values = request.intent()
    with psycopg.connect(migrated_database_url) as connection:
        for invalid in ("\t", "\u3000Approved", "Approved\n"):
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO app.termination_notices VALUES(%s,%s,%s,NULL,"
                        "'Approved content','Signed provision',clock_timestamp(),%s)",
                        (request.notice_id, lease, request.notice_date, human),
                    )
                    fields = NOTICE_TEXT_FIELDS[2:]
                    context = values | {field: invalid}
                    connection.execute(
                        "INSERT INTO app.lease_notice_contexts VALUES"
                        "(%s,%s,%s,%s,%s,%s,%s,%s,NULL)",
                        (
                            request.notice_id,
                            request.expected_lease_version,
                            *(context[name] for name in fields),
                        ),
                    )
        assert connection.execute(
            "SELECT count(*) FROM app.termination_notices WHERE id=%s",
            (request.notice_id,),
        ).fetchone() == (0,)
