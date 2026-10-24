"""Synthetic PostgreSQL invariants for separate warnings and Rent nonpayment."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ReverseCreditApplicationCommand
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import PostgresInvoiceService, VoidInvoiceCommand
from property_rental.lease_enforcement import (
    NONPAYMENT_EVENT,
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    WARNING_CREATE,
    WARNING_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementConflictError,
    LeaseEnforcementInvalidError,
    LeaseEnforcementKeyReused,
    LeaseEnforcementNotFoundError,
    LeaseEnforcementUnavailableError,
    NonpaymentEventKind,
    OpenRentNonpaymentCase,
    PostgresLeaseEnforcementService,
    RecordLeaseWarning,
    RecordRentNonpaymentEvent,
)
from property_rental.payment_allocation import PostAllocationsCommand, ReverseAllocationCommand
from test_billing_service_migration import (
    admin_database_url,
    authenticated,
    initial_command,
    setup_billing_source,
)
from test_credit_application_migration import application_id, designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credit_service
from test_customer_ledger_migration import assert_reconciled
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocation_service
from test_reservation_migration import migrated_database_url  # noqa: F401


def service() -> PostgresLeaseEnforcementService:
    return PostgresLeaseEnforcementService(runtime_database_url(), financial_database_url())


def staff(human: UUID, prop: UUID, *caps: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(cap, frozenset({str(prop)}))
            for cap in (
                caps
                or (
                    WARNING_READ,
                    WARNING_CREATE,
                    NONPAYMENT_READ,
                    NONPAYMENT_OPEN,
                    NONPAYMENT_EVENT,
                )
            )
        ),
    )


def source(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        today_row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
        assert today_row is not None and isinstance(today_row[0], date)
        today = today_row[0]
        period = (today.replace(day=1) - timedelta(days=40)).replace(day=1)
        human, prop, customer, lease = setup_signed_lease(
            connection,
            start_date=period.replace(month=1, day=1),
            end_date=today.replace(year=today.year + 1, month=12, day=31),
        )
        invoice, line = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=customer, lease_id=lease, period_start=period
        )
    return human, prop, customer, lease, invoice, line


def opened(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    human, prop, customer, lease, invoice, line = source(url)
    result = service().open_case(
        prop,
        lease,
        OpenRentNonpaymentCase(uuid4(), line, "Open Rent case"),
        actor=staff(human, prop),
        request_id="open",
    )
    data = cast(dict[str, object], result.body["data"])
    return human, prop, customer, lease, invoice, line, UUID(str(data["id"]))


def event(
    prop: UUID, lease: UUID, case: UUID, human: UUID, kind: NonpaymentEventKind
) -> dict[str, object]:
    request = RecordRentNonpaymentEvent(
        uuid4(),
        kind,
        "Authorized documented action",
        "Notice-001" if kind is NonpaymentEventKind.TWENTY_DAY_WARNING else None,
        "Delivered to Customer",
        "Management instruction" if kind is NonpaymentEventKind.AUTHORIZED_FOLLOW_UP else None,
    )
    result = service().record_event(
        prop, lease, case, request, actor=staff(human, prop), request_id="event"
    )
    return cast(dict[str, object], result.body["data"])


def test_warning_case_and_events_preserve_all_tenancy_and_financial_sources(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, invoice, line = source(migrated_database_url)
    flow, actor = service(), staff(human, prop)
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            (
                "SELECT to_jsonb(l),to_jsonb(u),to_jsonb(i),to_jsonb(il),to_jsonb(o) "
                "FROM app.leases l JOIN app.units u ON u.id=l.unit_id JOIN app.invoic"
                "es i ON i.lease_id=l.id JOIN app.invoice_lines il ON il.invoice_id=i"
                ".id JOIN app.occupancies o ON o.lease_id=l.id WHERE i.id=%s"
            ),
            (invoice,),
        ).fetchall()
    warning = RecordLeaseWarning(
        uuid4(),
        1,
        date(2026, 1, 1),
        date(2026, 1, 2),
        "Documented violation",
        "Signed Lease clause",
        "Letter delivered",
        "Document history",
    )
    result = flow.record_warning(prop, lease, warning, actor=actor, request_id="warning")
    assert flow.record_warning(prop, lease, warning, actor=actor, request_id="replay") == result
    with pytest.raises(LeaseEnforcementKeyReused):
        flow.record_warning(
            prop,
            lease,
            replace(warning, reason="Different intent"),
            actor=actor,
            request_id="changed",
        )
    with pytest.raises(LeaseEnforcementConflictError):
        flow.record_warning(
            prop,
            lease,
            replace(warning, idempotency_key=uuid4()),
            actor=actor,
            request_id="duplicate",
        )
    request = OpenRentNonpaymentCase(uuid4(), line, "Open case")
    opened_case = flow.open_case(prop, lease, request, actor=actor, request_id="case")
    assert (
        flow.open_case(prop, lease, request, actor=actor, request_id="case-replay") == opened_case
    )
    case = UUID(str(cast(dict[str, object], opened_case.body["data"])["id"]))
    notice = event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    default = event(prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT)
    event(prop, lease, case, human, NonpaymentEventKind.AUTHORIZED_FOLLOW_UP)
    assert notice["remaining_rent_usd_cents"] == default["remaining_rent_usd_cents"] == 80000
    assert default["customer_id"] == str(customer) and default["rent_invoice_line_id"] == str(line)
    assert flow.read(prop, lease, "WARNINGS", actor=actor)["total"] == 1
    assert flow.read(prop, lease, "EVENTS", case_id=case, actor=actor)["total"] == 3
    assert (
        len(
            cast(
                list[object],
                flow.read(prop, lease, "EVENTS", case_id=case, actor=actor, limit=1, offset=1)[
                    "items"
                ],
            )
        )
        == 1
    )
    with psycopg.connect(migrated_database_url) as connection:
        after = connection.execute(
            (
                "SELECT to_jsonb(l),to_jsonb(u),to_jsonb(i),to_jsonb(il),to_jsonb(o) "
                "FROM app.leases l JOIN app.units u ON u.id=l.unit_id JOIN app.invoic"
                "es i ON i.lease_id=l.id JOIN app.invoice_lines il ON il.invoice_id=i"
                ".id JOIN app.occupancies o ON o.lease_id=l.id WHERE i.id=%s"
            ),
            (invoice,),
        ).fetchall()
        assert before == after
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE lease_id=%s AND action=ANY(%s)",
            (lease, [WARNING_CREATE, NONPAYMENT_OPEN, NONPAYMENT_EVENT]),
        ).fetchone() == (5,)


@pytest.mark.parametrize(
    "day,warning,default",
    [
        (0, False, False),
        (1, False, False),
        (19, False, False),
        (20, True, False),
        (29, True, False),
        (30, True, True),
        (31, True, True),
    ],
)
def test_calendar_thresholds_use_rent_due_date_and_phnom_penh_midnight(
    migrated_database_url: str,  # noqa: F811
    day: int,
    warning: bool,
    default: bool,
) -> None:
    due = date(2026, 8, 5)
    instant = datetime(2026, 8, 4, 17, tzinfo=UTC) + timedelta(days=day)
    with psycopg.connect(migrated_database_url) as connection:
        for kind, expected in [
            ("TWENTY_DAY_WARNING", warning),
            ("THIRTY_DAY_SERIOUS_DEFAULT", default),
        ]:
            query = "SELECT app.rent_nonpayment_milestone_eligible(%s,%s,%s,%s,false)"
            assert connection.execute(query, (kind, due, instant, 1)).fetchone() == (expected,)
            assert connection.execute(query, (kind, due, instant, 0)).fetchone() == (False,)
            if day in (20, 30) and kind == (
                "TWENTY_DAY_WARNING" if day == 20 else "THIRTY_DAY_SERIOUS_DEFAULT"
            ):
                assert connection.execute(
                    query, (kind, due, instant - timedelta(microseconds=1), 1)
                ).fetchone() == (False,)


def test_payment_and_credit_applications_cure_rent_and_reversal_keeps_default_history(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        today_row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
        assert today_row is not None and isinstance(today_row[0], date)
        period = (today_row[0].replace(day=1) - timedelta(days=40)).replace(day=1)
    # Recognize actual excess before this Invoice exists; preserve the existing
    # prohibition on recognizing credit while payable obligations remain.
    human, prop, credit, invoice, line, _ = credit_source(
        migrated_database_url, amount=50000, period_start=period
    )
    with psycopg.connect(migrated_database_url) as connection:
        ids = connection.execute(
            "SELECT lease_id,customer_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert ids is not None
        lease, customer = UUID(str(ids[0])), UUID(str(ids[1]))
    opened_case = service().open_case(
        prop,
        lease,
        OpenRentNonpaymentCase(uuid4(), line, "Open case"),
        actor=staff(human, prop),
        request_id="open",
    )
    case = UUID(str(cast(dict[str, object], opened_case.body["data"])["id"]))
    event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    event(prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT)
    with psycopg.connect(migrated_database_url) as connection:
        pay = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=30000
        )
    allocation_service().post(
        prop,
        pay,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Customer identified Rent",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": 30000,
                        "details": [{"invoice_line_id": str(line), "amount_usd_cents": 30000}],
                    }
                ],
            },
        ),
        actor=allocation_actor(human, prop),
    )
    posted = credit_service().apply(
        prop,
        credit,
        designated(invoice, line, 50000),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    cure = event(prop, lease, case, human, NonpaymentEventKind.CURE)
    assert cure["remaining_rent_usd_cents"] == 0
    credit_service().reverse_application(
        prop,
        application_id(posted),
        ReverseCreditApplicationCommand(uuid4(), "Correct application"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    read = service().read(prop, lease, "CASE", case_id=case, actor=staff(human, prop))
    assessment = cast(dict[str, object], read["assessment"])
    assert assessment["remaining_rent"] == {"currency": "USD", "minor_units": 50000}
    assert assessment["serious_default_recorded"] is True
    assert assessment["thirty_day_default_eligible"] is False
    assert read["event_count"] == 3


@pytest.mark.parametrize(
    "kind", [NonpaymentEventKind.TWENTY_DAY_WARNING, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT]
)
@pytest.mark.parametrize("same_key", [True, False])
def test_same_key_and_different_key_concurrency_preserve_one_milestone(
    migrated_database_url: str,  # noqa: F811
    kind: NonpaymentEventKind,
    same_key: bool,
) -> None:
    human, prop, _, lease, _, _, case = opened(migrated_database_url)
    request = RecordRentNonpaymentEvent(
        uuid4(),
        kind,
        "Concurrent milestone",
        "Notice" if kind is NonpaymentEventKind.TWENTY_DAY_WARNING else None,
    )

    barrier = Barrier(2)

    def post(key: UUID) -> object:
        barrier.wait(timeout=5)
        try:
            return service().record_event(
                prop,
                lease,
                case,
                replace(request, idempotency_key=key),
                actor=staff(human, prop),
                request_id="race",
            )
        except LeaseEnforcementConflictError as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                post, [request.idempotency_key, request.idempotency_key if same_key else uuid4()]
            )
        )
    if same_key:
        assert results[0] == results[1] and not isinstance(results[0], str)
    else:
        assert sum(isinstance(result, str) for result in results) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        conflicts = list(pool.map(post, [uuid4(), uuid4()]))
    assert conflicts == ["LeaseEnforcementConflictError"] * 2
    assert (
        service().read(prop, lease, "EVENTS", case_id=case, actor=staff(human, prop))["total"] == 1
    )


def test_stale_actor_replay_and_wrong_lease_fail_closed(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, lease, _, line = source(migrated_database_url)
    request = OpenRentNonpaymentCase(uuid4(), line, "Open case")
    actor = staff(human, prop)
    service().open_case(prop, lease, request, actor=actor, request_id="first")
    with pytest.raises(LeaseEnforcementNotFoundError):
        service().open_case(prop, uuid4(), request, actor=actor, request_id="wrong")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        service().open_case(prop, lease, request, actor=actor, request_id="disabled")
    with pytest.raises(LeaseEnforcementAuthorizationError):
        service().read(prop, lease, "CASES", actor=actor)


@pytest.mark.parametrize(
    "table", ["rent_nonpayment_cases", "rent_nonpayment_events", "lease_enforcement_commands"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_new_history_is_immutable_and_runtime_has_no_direct_mutation(
    migrated_database_url: str,  # noqa: F811
    table: str,
    operation: str,
) -> None:
    human, prop, _, lease, _, _, case = opened(migrated_database_url)
    event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    from psycopg import sql

    query = sql.SQL(
        "TRUNCATE app.{}"
        if operation == "TRUNCATE"
        else "DELETE FROM app.{}"
        if operation == "DELETE"
        else "UPDATE app.{} SET "
        + (
            "reason=reason"
            if table == "rent_nonpayment_events"
            else "request_digest=request_digest"
            if table == "lease_enforcement_commands"
            else "opened_at=opened_at"
        )
    ).format(sql.Identifier(table))
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(query)
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(query)


def test_runtime_cannot_execute_commands_or_internal_unscoped_reads(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(runtime_database_url()) as connection:
        assert connection.execute(
            "SELECT has_function_privilege(current_user,'app.lease_enforcement_co"
            "mmand(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text)','EXECUTE'),has"
            "_function_privilege(current_user,'app.rent_nonpayment_case_snapshot("
            "uuid,timestamptz)','EXECUTE')"
        ).fetchone() == (False, False)


def test_forward_upgrade_preserves_existing_warning_and_refuses_downgrade(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("lease_enforcement_upgrade") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260909_49")
        human, _, _, lease, invoice, _ = source(temporary)
        warning_id = uuid4()
        with psycopg.connect(temporary) as connection:
            connection.execute(
                (
                    "INSERT INTO app.lease_violation_warnings VALUES(%s,%s,1,'2026-01-01'"
                    ",'2026-01-02','Violation','Signed clause','Letter evidence',clock_ti"
                    "mestamp(),%s)"
                ),
                (warning_id, lease, human),
            )
            before = connection.execute(
                (
                    "SELECT to_jsonb(w),to_jsonb(i) FROM app.lease_violation_warnings w C"
                    "ROSS JOIN app.invoices i WHERE w.id=%s AND i.id=%s"
                ),
                (warning_id, invoice),
            ).fetchone()
        alembic_command.upgrade(config, "head")
        with psycopg.connect(temporary) as connection:
            assert (
                connection.execute(
                    (
                        "SELECT to_jsonb(w),to_jsonb(i)-ARRAY['due_date_override_reason',"
                        "'due_date_set_by','due_date_set_at','draft_reference'] "
                        "FROM app.lease_violation_warnings w "
                        "CROSS JOIN app.invoices i WHERE w.id=%s AND i.id=%s"
                    ),
                    (warning_id, invoice),
                ).fetchone()
                == before
            )
        with pytest.raises(RuntimeError, match="forward-only"):
            alembic_command.downgrade(config, "20260909_49")


def test_mixed_service_balance_cannot_trigger_rent_default_after_rent_cure(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, occupancy = setup_billing_source(connection)
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy), actor=authenticated(human, prop)
    )
    with psycopg.connect(migrated_database_url) as connection:
        lines: dict[str, UUID] = dict(
            connection.execute(
                "SELECT category,id FROM app.invoice_lines "
                "WHERE invoice_id=%s ORDER BY line_sequence",
                (issued.invoice_id,),
            ).fetchall()
        )
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=issued.rent_usd_cents,
        )
    flow, actor = service(), staff(human, prop)
    with pytest.raises(LeaseEnforcementConflictError):
        flow.open_case(
            prop,
            lease,
            OpenRentNonpaymentCase(uuid4(), lines["SERVICE_CHARGES"], "Wrong source"),
            actor=actor,
            request_id="service",
        )
    # DL-064 (BR-LEASE-026): the Initial Rent Invoice never opens a Rent nonpayment case;
    # the mixed Rent and Service cure path is covered on recurring Rent in
    # test_rent_nonpayment_recurring_only_migration.py.
    with pytest.raises(LeaseEnforcementConflictError):
        flow.open_case(
            prop,
            lease,
            OpenRentNonpaymentCase(uuid4(), lines["RENT"], "Rent only"),
            actor=actor,
            request_id="rent",
        )
    del payment


def test_event_waits_for_financial_lock_and_rechecks_committed_zero_rent(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, invoice, line, case = opened(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=80000
        )
    intent = {
        "mode": "DESIGNATED",
        "designation_reference": "Pay identified Rent",
        "targets": [
            {
                "invoice_id": str(invoice),
                "amount_usd_cents": 80000,
                "details": [{"invoice_line_id": str(line), "amount_usd_cents": 80000}],
            }
        ],
    }
    application_name = f"v1054-event-lock-{uuid4().hex}"
    flow = PostgresLeaseEnforcementService(
        runtime_database_url(),
        make_conninfo(financial_database_url(), application_name=application_name),
    )
    request = RecordRentNonpaymentEvent(
        uuid4(), NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT, "Concurrent default"
    )
    with psycopg.connect(migrated_database_url) as holding:
        holding.execute("SELECT id FROM app.invoices WHERE id=%s FOR UPDATE", (invoice,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                flow.record_event,
                prop,
                lease,
                case,
                request,
                actor=staff(human, prop),
                request_id="locked-event",
            )
            observed = False
            try:
                with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        waiting = observer.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity "
                            "WHERE application_name=%s AND datname=%s "
                            "AND wait_event_type='Lock' "
                            "AND %s=ANY(pg_catalog.pg_blocking_pids(pid)))",
                            (application_name, holding.info.dbname, holding.info.backend_pid),
                        ).fetchone()
                        if waiting == (True,):
                            observed = True
                            break
                        time.sleep(0.01)
                assert observed, "The event transaction must wait on the shared Invoice lock"
                # A complete Payment application, not a prohibited zero-principal Adjustment,
                # settles the Invoice while the nonpayment request waits.
                holding.execute(
                    "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
                    (prop, payment, human, uuid4(), "a" * 64, Jsonb(intent)),
                )
                holding.execute("SET CONSTRAINTS ALL IMMEDIATE")
                holding.commit()
                with pytest.raises(LeaseEnforcementConflictError):
                    future.result(timeout=5)
            finally:
                holding.rollback()
    assert (
        service().read(prop, lease, "EVENTS", case_id=case, actor=staff(human, prop))["total"] == 0
    )


def test_case_receipt_rolls_back_when_audit_cannot_be_written(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, line = source(migrated_database_url)
    key = uuid4()
    request = OpenRentNonpaymentCase(key, line, "Audited action")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "CREATE FUNCTION app.test_enforcement_audit_failure() RETURNS trigger"
            " LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='rent_nonpayment.case_ma"
            "nage' THEN RAISE EXCEPTION 'Synthetic audit failure'; END IF; RETURN"
            " NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER test_enforcement_audit_failure BEFORE INSERT ON app.a"
            "udit_events FOR EACH ROW EXECUTE FUNCTION app.test_enforcement_audit"
            "_failure()"
        )
    try:
        with pytest.raises(LeaseEnforcementUnavailableError):
            service().open_case(
                prop, lease, request, actor=staff(human, prop), request_id="audit-failure"
            )
        with psycopg.connect(migrated_database_url) as connection:
            assert connection.execute(
                ("SELECT count(*) FROM app.rent_nonpayment_cases WHERE rent_invoice_line_id=%s"),
                (line,),
            ).fetchone() == (0,)
            assert connection.execute(
                ("SELECT count(*) FROM app.lease_enforcement_commands WHERE idempotency_key=%s"),
                (key,),
            ).fetchone() == (0,)
    finally:
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute("DROP TRIGGER test_enforcement_audit_failure ON app.audit_events")
            connection.execute("DROP FUNCTION app.test_enforcement_audit_failure()")
    recovered = service().open_case(
        prop, lease, request, actor=staff(human, prop), request_id="recover"
    )
    assert (
        service().open_case(prop, lease, request, actor=staff(human, prop), request_id="replay")
        == recovered
    )


def test_direct_case_source_snapshot_and_future_timestamp_constraints(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, invoice, line = source(migrated_database_url)
    for change in ("future", "due", "customer", "line"):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(
                    (
                        "INSERT INTO app.rent_nonpayment_cases SELECT %s,%s,%s,id,%s,due_date"
                        "+%s,clock_timestamp()+(%s||' seconds')::interval,%s FROM app.invoice"
                        "s WHERE id=%s"
                    ),
                    (
                        uuid4(),
                        lease,
                        uuid4() if change == "customer" else customer,
                        uuid4() if change == "line" else line,
                        1 if change == "due" else 0,
                        3600 if change == "future" else 0,
                        human,
                        invoice,
                    ),
                )
    assert service().read(prop, lease, "CASES", actor=staff(human, prop))["total"] == 0


def test_cure_requires_prior_milestone_and_zero_balance_and_events_reject_void_source(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, invoice, line, case = opened(migrated_database_url)
    with pytest.raises(LeaseEnforcementConflictError):
        event(prop, lease, case, human, NonpaymentEventKind.CURE)
    adjustment = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
            "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES(%s,%s,%s,'CREDIT',10000,"
            "'correction','Documented correction',clock_timestamp(),%s,'invoices.adjust')",
            (adjustment, invoice, line, human),
        )
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=70000
        )
    snapshot = service().read(prop, lease, "CASE", case_id=case, actor=staff(human, prop))
    assert cast(dict[str, object], snapshot["assessment"])["remaining_rent"] == {
        "currency": "USD",
        "minor_units": 70000,
    }
    posted = allocation_service().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Rent instruction",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": 70000,
                        "details": [{"invoice_line_id": str(line), "amount_usd_cents": 70000}],
                    }
                ],
            },
        ),
        actor=allocation_actor(human, prop),
    )
    with pytest.raises(LeaseEnforcementConflictError):
        event(prop, lease, case, human, NonpaymentEventKind.CURE)
    identities = posted["allocation_ids"]
    assert isinstance(identities, list) and len(identities) == 1
    allocation_service().reverse_allocation(
        prop,
        UUID(str(identities[0])),
        ReverseAllocationCommand(uuid4(), "Resolve allocation before VOID"),
        actor=allocation_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.invoice_adjustment_reversals SELECT %s,id,"
            "'Resolved adjustment before VOID',clock_timestamp(),%s,"
            "'invoices.adjustments.reverse' FROM app.invoice_adjustments WHERE id=%s",
            (uuid4(), human, adjustment),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert version is not None
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Approved source cancellation", int(version[0])),
        actor=invoice_api_actor(human, prop),
    )
    history = service().read(prop, lease, "CASE", case_id=case, actor=staff(human, prop))
    assert cast(dict[str, object], history["assessment"])["source_applicable"] is False
    assert cast(dict[str, object], history["assessment"])["remaining_rent"] == {
        "currency": "USD",
        "minor_units": 0,
    }
    for kind in (
        NonpaymentEventKind.TWENTY_DAY_WARNING,
        NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT,
        NonpaymentEventKind.CURE,
    ):
        with pytest.raises(LeaseEnforcementConflictError):
            event(prop, lease, case, human, kind)
    follow_up = event(prop, lease, case, human, NonpaymentEventKind.AUTHORIZED_FOLLOW_UP)
    assert follow_up["remaining_rent_usd_cents"] == 0


def test_concurrent_case_keys_resolve_to_one_per_rent_line(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, line = source(migrated_database_url)
    barrier = Barrier(2)

    def create(_: int) -> object:
        barrier.wait(timeout=5)
        try:
            return service().open_case(
                prop,
                lease,
                OpenRentNonpaymentCase(uuid4(), line, "Concurrent open"),
                actor=staff(human, prop),
                request_id="open",
            )
        except LeaseEnforcementConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [0, 1]))
    assert sum(result == "conflict" for result in results) == 1
    assert service().read(prop, lease, "CASES", actor=staff(human, prop))["total"] == 1


def test_cure_after_day_twenty_warning_stops_day_thirty_trigger_and_preserves_notice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
        assert row is not None and isinstance(row[0], date)
        move_in = row[0] - timedelta(days=25)
        human, prop, customer, lease, occupancy = setup_billing_source(
            connection,
            configure_trash=False,
            configure_internet=False,
            move_in_date=move_in,
            lease_end_date=move_in.replace(year=move_in.year + 1),
        )
    issued_at = datetime(
        move_in.year, move_in.month, move_in.day, 0, 0, 1, tzinfo=ZoneInfo("Asia/Phnom_Penh")
    )
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy, period_start=move_in, issued_at=issued_at),
        actor=authenticated(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        line_row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s AND category='RENT'",
            (issued.invoice_id,),
        ).fetchone()
        assert line_row is not None
        line = UUID(str(line_row[0]))
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=issued.rent_usd_cents,
        )
    # DL-064 (BR-LEASE-026): the Initial Rent Invoice never opens a Rent nonpayment case;
    # cure before day 30 is covered on recurring Rent in
    # test_rent_nonpayment_recurring_only_migration.py.
    flow, actor = service(), staff(human, prop)
    with pytest.raises(LeaseEnforcementConflictError):
        flow.open_case(
            prop,
            lease,
            OpenRentNonpaymentCase(uuid4(), line, "Day20 case"),
            actor=actor,
            request_id="day20",
        )
    del payment


def test_event_commands_reject_forged_client_balance_and_milestone_date(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, _, case = opened(migrated_database_url)
    for field, value in [
        ("event_date", "2999-01-01"),
        ("remaining_rent_usd_cents", 0),
        ("occurred_at", "2999-01-01T00:00:00Z"),
    ]:
        intent = {
            "reason": "Forged derived source",
            "event_kind": "THIRTY_DAY_SERIOUS_DEFAULT",
            field: value,
        }
        with psycopg.connect(financial_database_url()) as connection:
            with pytest.raises(psycopg.Error) as error:
                connection.execute(
                    "SELECT app.lease_enforcement_command(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (prop, lease, case, human, "EVENT", uuid4(), "b" * 64, Jsonb(intent), "forged"),
                )
            assert error.value.sqlstate == "P5402"
    assert (
        service().read(prop, lease, "EVENTS", case_id=case, actor=staff(human, prop))["total"] == 0
    )


def test_void_case_reconciles_current_rent_and_preserves_authorized_follow_up_history(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, invoice, line, case = opened(migrated_database_url)
    flow, actor = service(), staff(human, prop)
    event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    event(prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT)
    original_events = flow.read(prop, lease, "EVENTS", case_id=case, actor=actor)["items"]
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None
    canceled = PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Authorized source cancellation", int(row[0])),
        actor=invoice_api_actor(human, prop),
    )
    assessment = cast(
        dict[str, object], flow.read(prop, lease, "CASE", case_id=case, actor=actor)["assessment"]
    )
    assert assessment["source_applicable"] is False
    assert (
        assessment["remaining_rent"]
        == canceled["outstanding_balance"]
        == {"currency": "USD", "minor_units": 0}
    )
    assert assessment["warning_recorded"] is assessment["serious_default_recorded"] is True
    assert all(
        assessment[key] is False
        for key in ("twenty_day_warning_eligible", "thirty_day_default_eligible", "cure_eligible")
    )
    assert flow.read(prop, lease, "EVENTS", case_id=case, actor=actor)["items"] == original_events
    source_query = (
        "SELECT to_jsonb(i),to_jsonb(il),to_jsonb(l),to_jsonb(u),to_jsonb(o) "
        "FROM app.invoices i JOIN app.invoice_lines il ON il.invoice_id=i.id "
        "JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id "
        "JOIN app.occupancies o ON o.lease_id=l.id WHERE i.id=%s"
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer).invoice == 0
        assert connection.execute(
            "SELECT amount_usd_cents FROM app.invoice_lines WHERE id=%s", (line,)
        ).fetchone() == (80000,)
        before = connection.execute(source_query, (invoice,)).fetchall()
    with pytest.raises(LeaseEnforcementInvalidError):
        RecordRentNonpaymentEvent(
            uuid4(), NonpaymentEventKind.AUTHORIZED_FOLLOW_UP, "Missing authority"
        )
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as missing:
            connection.execute(
                "SELECT app.lease_enforcement_command(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    lease,
                    case,
                    human,
                    "EVENT",
                    uuid4(),
                    "a" * 64,
                    Jsonb({"event_kind": "AUTHORIZED_FOLLOW_UP", "reason": "Missing authority"}),
                    "missing",
                ),
            )
        assert missing.value.sqlstate == "P5402"
    request = RecordRentNonpaymentEvent(
        uuid4(),
        NonpaymentEventKind.AUTHORIZED_FOLLOW_UP,
        "Explain canceled source",
        authorization_reference="Management instruction after cancellation",
    )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        flow.record_event(
            prop,
            lease,
            case,
            request,
            actor=staff(human, prop, WARNING_CREATE),
            request_id="wrong-capability",
        )
    with pytest.raises(LeaseEnforcementNotFoundError):
        flow.record_event(prop, uuid4(), case, request, actor=actor, request_id="wrong-lease")
    followed = flow.record_event(
        prop,
        lease,
        case,
        request,
        actor=staff(human, prop, NONPAYMENT_EVENT),
        request_id="follow-up",
    )
    assert (
        flow.record_event(prop, lease, case, request, actor=actor, request_id="replay") == followed
    )
    data = cast(dict[str, object], followed.body["data"])
    assert data["remaining_rent_usd_cents"] == 0
    assert data["event_kind"] == "AUTHORIZED_FOLLOW_UP"
    retained = cast(
        list[dict[str, object]],
        flow.read(prop, lease, "EVENTS", case_id=case, actor=actor)["items"],
    )
    assert retained[:2] == original_events and len(retained) == 3
    assert [item["remaining_rent_usd_cents"] for item in retained] == [80000, 80000, 0]
    with pytest.raises(LeaseEnforcementConflictError):
        event(prop, lease, case, human, NonpaymentEventKind.CURE)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(source_query, (invoice,)).fetchall() == before
        assert assert_reconciled(connection, customer).invoice == 0
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action='rent_nonpayment.event_post'",
            (UUID(str(data["id"])),),
        ).fetchone() == (1,)
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        flow.record_event(prop, lease, case, request, actor=actor, request_id="stale-replay")


def test_follow_up_waits_for_source_void_and_enforces_cancellation_chronology(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, invoice, _, case = opened(migrated_database_url)
    application_name = f"v1054-void-follow-up-{uuid4().hex}"
    flow = PostgresLeaseEnforcementService(
        runtime_database_url(),
        make_conninfo(financial_database_url(), application_name=application_name),
    )
    request = RecordRentNonpaymentEvent(
        uuid4(),
        NonpaymentEventKind.AUTHORIZED_FOLLOW_UP,
        "Document source cancellation",
        authorization_reference="Management instruction",
    )
    with psycopg.connect(migrated_database_url) as holding:
        version = holding.execute(
            "SELECT version FROM app.invoices WHERE id=%s FOR UPDATE", (invoice,)
        ).fetchone()
        assert version is not None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                flow.record_event,
                prop,
                lease,
                case,
                request,
                actor=staff(human, prop),
                request_id="waiting-follow-up",
            )
            try:
                observed = False
                with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        row = observer.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity "
                            "WHERE application_name=%s AND datname=%s AND wait_event_type='Lock' "
                            "AND %s=ANY(pg_catalog.pg_blocking_pids(pid)))",
                            (application_name, holding.info.dbname, holding.info.backend_pid),
                        ).fetchone()
                        if row == (True,):
                            observed = True
                            break
                        time.sleep(0.01)
                assert observed, "Follow-up must wait for the exact source Invoice lock"
                holding.execute(
                    "SELECT app.void_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        prop,
                        invoice,
                        human,
                        uuid4(),
                        "c" * 64,
                        int(version[0]),
                        "Authorized source cancellation",
                        uuid4(),
                        uuid4(),
                    ),
                )
                holding.execute("SET CONSTRAINTS ALL IMMEDIATE")
                with pytest.raises(psycopg.Error) as chronology:
                    with holding.transaction():
                        holding.execute(
                            "INSERT INTO app.rent_nonpayment_events "
                            "SELECT %s,%s,'AUTHORIZED_FOLLOW_UP', "
                            "timezone('Asia/Phnom_Penh',"
                            "v.occurred_at-interval '1 microsecond')::date, "
                            "0,NULL,NULL,'Backdated follow-up',"
                            "v.occurred_at-interval '1 microsecond', "
                            "%s,'Management instruction' FROM app.invoice_void_events v "
                            "WHERE v.invoice_id=%s",
                            (uuid4(), case, human, invoice),
                        )
                assert chronology.value.sqlstate == "23514"
                holding.commit()
                result = future.result(timeout=5)
            finally:
                holding.rollback()
    data = cast(dict[str, object], result.body["data"])
    assert data["remaining_rent_usd_cents"] == 0
    assert (
        flow.record_event(
            prop, lease, case, request, actor=staff(human, prop), request_id="exact-replay"
        )
        == result
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT e.occurred_at>=v.occurred_at,e.remaining_rent_usd_cents "
            "FROM app.rent_nonpayment_events e JOIN app.rent_nonpayment_cases c "
            "ON c.id=e.rent_nonpayment_case_id JOIN app.invoice_void_events v "
            "ON v.invoice_id=c.invoice_id WHERE c.id=%s",
            (case,),
        ).fetchall() == [(True, 0)]
