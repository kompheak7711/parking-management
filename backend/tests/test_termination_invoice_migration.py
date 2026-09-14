"""Real original coverage, financial changes, authorization and additive migration."""

from datetime import date
from pathlib import Path
from types import TracebackType
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg import Connection, Cursor
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ReverseCreditApplicationCommand
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    PostgresInvoiceService,
    VoidInvoiceCommand,
)
from property_rental.lease_termination import TerminationBasis
from property_rental.payment_allocation import ReverseAllocationCommand
from property_rental.termination_invoice import (
    OriginalRentCoverage,
    PostgresTerminationInvoiceReadService,
    TerminationInvoiceAuthorizationError,
    TerminationInvoiceLine,
    TerminationInvoiceNotFoundError,
)
from termination_test_support import terminate_test_lease
from test_billing_service_migration import (
    _processed_final_month_request,
    _processed_final_month_source,
    authenticated,
    initial_command,
    setup_billing_source,
)
from test_credit_application_migration import application_id
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as source_with_prior_credit
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
)
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import actor as payment_actor
from test_payment_allocation_migration import designated as payment_designated
from test_payment_allocation_migration import service as payments
from test_termination_deposit_migration import history, terminate


def reader(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(cap, frozenset({str(prop)})) for cap in ("leases.read", "invoices.read")
        ),
    )


def source(
    url: str, *, months: tuple[int, ...] = (7,), terminated: bool = True
) -> tuple[UUID, UUID, UUID, UUID, list[tuple[UUID, UUID]]]:
    with psycopg.connect(url) as connection:
        human, prop, customer, lease, _ = _processed_final_month_source(
            connection, date(2026, 7, 1), terminate=False
        )
        invoices = [
            create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=date(2026, month, 1),
            )
            for month in months
        ]
    if terminated:
        terminate(url, human, prop, lease, date(2026, 7, 10))
    return human, prop, customer, lease, invoices


@pytest.mark.parametrize(
    "actual,coverage",
    [
        (date(2026, 7, 28), OriginalRentCoverage.FINAL_AND_LATER_MONTHS),
        (date(2026, 8, 10), OriginalRentCoverage.FINAL_MONTH),
    ],
)
def test_initial_coverage_components_and_services_survive_termination_and_exact_replay(
    migrated_database_url: str, actual: date, coverage: OriginalRentCoverage
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, lease, occupancy = setup_billing_source(connection)
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    command = initial_command(lease, occupancy)
    original = flow.generate(command, actor=authenticated(human, prop))
    event = terminate(migrated_database_url, human, prop, lease, actual)
    with psycopg.connect(migrated_database_url) as connection:
        before = history(connection)
    result = PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
        lease, actor=reader(human, prop)
    )
    assert result.termination_event_id == event
    assert result.full_final_month_rent_usd_cents == 80000
    rent = next(row for row in result.items if row.category == "RENT")
    assert rent.original_rent_coverage is coverage
    assert rent.original_usd_cents == 92903 and rent.rent_billing_kind == "INITIAL"
    assert [(c.amount_usd_cents, c.period_start, c.period_end) for c in rent.components] == [
        (12903, date(2026, 7, 27), date(2026, 7, 31)),
        (80000, date(2026, 8, 1), date(2026, 8, 31)),
    ]
    services = [row for row in result.items if row.category == "SERVICE_CHARGES"]
    assert services and all(
        row.original_rent_coverage is OriginalRentCoverage.NON_RENT_SOURCE_REVIEW
        for row in services
    )
    assert (
        result.financial_completion_assessed
        is result.financial_dependencies_fully_assessed
        is False
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before
    assert flow.generate(command, actor=authenticated(human, prop)) == original


def test_final_and_future_original_lines_paginate_without_hiding_void_history(
    migrated_database_url: str,
) -> None:
    human, prop, _, lease, invoices = source(migrated_database_url, months=(7, 8, 9))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    pages: list[TerminationInvoiceLine] = []
    cursor = None
    while True:
        page = read.page(lease, actor=reader(human, prop), limit=1, after_line_id=cursor)
        pages.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        assert len(pages) <= 3
    assert len(pages) == 3
    assert [x.invoice_line_id for x in pages] == sorted(line for _, line in invoices)
    assert {x.period_start: x.original_rent_coverage for x in pages} == {
        date(2026, 7, 1): OriginalRentCoverage.FINAL_MONTH,
        date(2026, 8, 1): OriginalRentCoverage.LATER_MONTHS,
        date(2026, 9, 1): OriginalRentCoverage.LATER_MONTHS,
    }
    target = next(x for x in pages if x.period_start == date(2026, 8, 1))
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        target.invoice_id,
        VoidInvoiceCommand(uuid4(), "Approved invalid advance period", target.invoice_version),
        actor=invoice_api_actor(human, prop),
    )
    changed = read.page(lease, actor=reader(human, prop))
    voided = next(x for x in changed.items if x.invoice_id == target.invoice_id)
    assert (voided.original_usd_cents, voided.outstanding_usd_cents) == (80000, 0)
    assert voided.original_rent_coverage is OriginalRentCoverage.VOID_HISTORY
    assert changed.financial_completion_assessed is False


def test_payment_credit_adjustment_and_reversals_are_distinct_current_positions(
    migrated_database_url: str,
) -> None:
    # Recognize valid prior excess before this Invoice creates a due obligation.
    human, prop, credit, invoice, line, _ = source_with_prior_credit(
        migrated_database_url, amount=20000, period_start=date(2026, 7, 1)
    )
    with psycopg.connect(migrated_database_url) as connection:
        identities = connection.execute(
            "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert identities is not None
        customer, lease = identities
        assert isinstance(customer, UUID) and isinstance(lease, UUID)
        paid = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=20000
        )
    terminate(migrated_database_url, human, prop, lease, date(2026, 7, 10))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    posted = payments().post(
        prop, paid, payment_designated(invoice, line, 10000), actor=payment_actor(human, prop)
    )
    applied = credits().apply(
        prop,
        credit,
        credit_designated(invoice, line, 10000),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    row = read.page(lease, actor=reader(human, prop)).items[0]
    assert (
        row.original_usd_cents,
        row.adjusted_usd_cents,
        row.payment_applied_usd_cents,
        row.credit_applied_usd_cents,
        row.outstanding_usd_cents,
    ) == (80000, 80000, 10000, 10000, 60000)
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.CREDIT,
            5000,
            "approved/correction",
            "Approved reduction preserves the original charge",
            row.invoice_version,
        ),
        actor=invoice_api_actor(human, prop),
    )
    adjusted = read.page(lease, actor=reader(human, prop)).items[0]
    assert (
        adjusted.adjusted_usd_cents,
        adjusted.active_adjustment_count,
        adjusted.outstanding_usd_cents,
    ) == (75000, 1, 55000)
    ids = posted["allocation_ids"]
    assert isinstance(ids, list) and len(ids) == 1
    payments().reverse_allocation(
        prop,
        UUID(str(ids[0])),
        ReverseAllocationCommand(uuid4(), "Approved attribution correction"),
        actor=payment_actor(human, prop),
    )
    credits().reverse_application(
        prop,
        application_id(applied),
        ReverseCreditApplicationCommand(uuid4(), "Approved attribution correction"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    final = read.page(lease, actor=reader(human, prop)).items[0]
    assert (
        final.original_usd_cents,
        final.adjusted_usd_cents,
        final.payment_applied_usd_cents,
        final.credit_applied_usd_cents,
        final.outstanding_usd_cents,
    ) == (80000, 75000, 0, 0, 75000)


def test_open_read_snapshot_stays_coherent_when_a_payment_is_posted_elsewhere(
    migrated_database_url: str,
) -> None:
    human, prop, customer, lease, invoices = source(migrated_database_url)
    invoice, line = invoices[0]
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=10000
        )
    query = "SELECT app.lease_termination_invoice_readiness(%s,%s,%s,%s,%s)"
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        original = connection.execute(query, (prop, lease, human, 50, None)).fetchone()
        assert original is not None
        payments().post(
            prop,
            payment,
            payment_designated(invoice, line, 10000),
            actor=payment_actor(human, prop),
        )
        later = connection.execute(query, (prop, lease, human, 50, None)).fetchone()
        assert later is not None and later[0]["items"] == original[0]["items"]
    current = PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
        lease, actor=reader(human, prop)
    )
    assert current.items[0].payment_applied_usd_cents == 10000
    assert current.items[0].outstanding_usd_cents == 70000


def test_signed_other_and_unterminated_sources_do_not_establish_voluntary_rent(
    migrated_database_url: str,
) -> None:
    human, prop, _, lease, _ = source(migrated_database_url, terminated=False)
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    assert read.page(lease, actor=reader(human, prop)).evidence_status == "NO_TERMINATION"
    terminate(migrated_database_url, human, prop, lease, date(2026, 7, 10), voluntary=False)
    result = read.page(lease, actor=reader(human, prop))
    assert result.evidence_status == "SIGNED_TERMS_REVIEW_REQUIRED"
    assert result.full_final_month_rent_usd_cents is None


def test_generated_final_month_source_and_original_replay_are_preserved(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, lease, _ = _processed_final_month_source(
            connection, date(2026, 7, 1), terminate=False
        )
    command = _processed_final_month_request(lease, date(2026, 7, 1))
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    original = flow.generate(command, actor=authenticated(human, prop))
    terminate(migrated_database_url, human, prop, lease, date(2026, 7, 10))
    row = (
        PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
        .page(lease, actor=reader(human, prop))
        .items[0]
    )
    assert row.invoice_id == original.invoice_id and row.original_usd_cents == 80000
    assert row.original_rent_coverage is OriginalRentCoverage.FINAL_MONTH
    assert flow.generate(command, actor=authenticated(human, prop)) == original


def test_actual_transaction_permissions_and_fresh_actor_and_property_checks(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, lease, _ = source(migrated_database_url)
    connect = psycopg.connect
    observations: list[tuple[object, ...]] = []

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
            if query.startswith("SELECT app.lease_termination_invoice_readiness"):
                row = self.raw.execute(
                    "SELECT current_setting('transaction_read_only'),current_setting('"
                    "transaction_isolation'),"
                    "current_setting('lock_timeout'),current_setting('statement_timeou"
                    "t'),current_setting('TimeZone')"
                ).fetchone()
                assert row is not None
                observations.append(row)
            return self.raw.execute(query, params)

    def checked_connect(conninfo: str, *, connect_timeout: int) -> CheckedConnection:
        assert connect_timeout == 3
        return CheckedConnection(connect(conninfo, connect_timeout=connect_timeout))

    monkeypatch.setattr(psycopg, "connect", checked_connect)
    PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
        lease, actor=reader(human, prop)
    )
    assert observations == [("on", "repeatable read", "3s", "5s", "UTC")]
    monkeypatch.setattr(psycopg, "connect", connect)
    wrong = uuid4()
    with pytest.raises(TerminationInvoiceNotFoundError):
        PostgresTerminationInvoiceReadService(runtime_database_url(), wrong).page(
            lease, actor=reader(human, wrong)
        )
    with connect(migrated_database_url) as owner:
        owner.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(TerminationInvoiceAuthorizationError):
        PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
            lease, actor=reader(human, prop)
        )
    with connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT p.provolatile,p.prosecdef,p.proconfig,"
            "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),has_functio"
            "n_privilege('prm_financial',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE') FROM pg_catalog.pg_proc p "
            "WHERE p.oid='app.lease_termination_invoice_readiness(uuid,uuid,uu"
            "id,integer,uuid)'::regprocedure"
        ).fetchone() == ("s", True, ["search_path=pg_catalog"], True, True, False)


def test_forward59_preserves_every58_table_function_and_genuine_legacy_source(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    functions_query = (
        "SELECT p.oid,pg_catalog.pg_get_functiondef(p.oid),p.proacl::text,p.proowner "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    with (
        _temporary_migration_database("invoice_readiness") as temporary,
        monkeypatch.context() as environment,
    ):
        name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv("APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=name))
        environment.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=name)
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260914_53")
        human, prop, _, lease, _ = source(temporary, terminated=False)
        with psycopg.connect(temporary) as connection:
            version = connection.execute(
                "SELECT version FROM app.leases WHERE id=%s", (lease,)
            ).fetchone()
            assert version is not None
            terminate_test_lease(
                connection,
                property_id=prop,
                actor_id=human,
                lease_id=lease,
                expected_version=int(str(version[0])),
                actual_date=date(2026, 7, 10),
                governing="BR-LEASE-021",
                reason="Original approved legacy termination",
                basis=TerminationBasis.VOLUNTARY_EARLY,
                request_digest="e" * 64,
                legacy=True,
            )
        alembic_command.upgrade(config, "20260914_58")
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            functions = {row[0]: row[1:] for row in connection.execute(functions_query)}
        alembic_command.upgrade(config, "20260914_59")
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before
            after = {row[0]: row[1:] for row in connection.execute(functions_query)}
            assert all(after[oid] == data for oid, data in functions.items())
            assert len(after.keys() - functions.keys()) == 1
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260914_59",
            )
        result = PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
            lease, actor=reader(human, prop)
        )
        assert (
            result.evidence_status == "VOLUNTARY_EARLY_VERIFIED"
            and result.termination_event_id is not None
        )
        assert result.full_final_month_rent_usd_cents == 80000
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before
