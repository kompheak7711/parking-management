"""Real original coverage, financial changes, authorization and additive migration."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Barrier
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
    CreateInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceIdempotencyKeyReused,
    InvoiceInvalidError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
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
from test_lease_migration import create_draft, setup_sources, sign_lease
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
    assert final.invoice_status == "UNPAID"
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.CREDIT,
            75000,
            "approved/zero-obligation",
            "Approved correction removes the remaining obligation",
            final.invoice_version,
        ),
        actor=invoice_api_actor(human, prop),
    )
    zero = read.page(lease, actor=reader(human, prop)).items[0]
    assert zero.invoice_status == "PAID" and zero.original_usd_cents == 80000
    assert (
        zero.adjusted_usd_cents,
        zero.payment_applied_usd_cents,
        zero.credit_applied_usd_cents,
        zero.outstanding_usd_cents,
    ) == (0, 0, 0, 0)


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
        # V1-056 sub-slice 8a-1: the current reader expects the migration 86 line field
        # deposit_applied_usd_cents, so the revision 59 read is checked through its database
        # function as the runtime role; the asserted facts are unchanged.
        with psycopg.connect(runtime_database_url()) as connection:
            found = connection.execute(
                "SELECT app.lease_termination_invoice_readiness(%s,%s,%s,50,NULL)",
                (prop, lease, human),
            ).fetchone()
        assert found is not None
        result = found[0]
        assert (
            result["evidence_status"] == "VOLUNTARY_EARLY_VERIFIED"
            and result["termination_event_id"] is not None
        )
        assert result["full_final_month_rent_usd_cents"] == 80000
        with psycopg.connect(temporary) as connection:
            assert history(connection) == before


@pytest.mark.parametrize("issued", [False, True])
def test_distinct_signed_invoice_customers_preserve_identity_and_invalid_scope_rejection(
    migrated_database_url: str, issued: bool
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, unit, primary, other = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=primary,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        connection.execute(
            "INSERT INTO app.lease_signers(id,lease_id,customer_id,signed_at,added_by) "
            "VALUES (%s,%s,%s,statement_timestamp(),%s)",
            (uuid4(), lease, other, human),
        )
        sign_lease(connection, lease, human)
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,"
            "updated_by) VALUES (%s,%s,%s,'2026-01-01',%s,%s)",
            (uuid4(), lease, primary, human, human),
        )
        rent_invoice, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=primary,
            lease_id=lease,
            period_start=date(2026, 7, 1),
        )
        outsider = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES "
            "(%s,'Unrelated synthetic Customer',%s,%s)",
            (outsider, human, human),
        )
        before_invalid = history(connection)
        with pytest.raises(psycopg.Error) as invalid:
            with connection.transaction():
                create_recurring_rent_invoice(
                    connection,
                    actor_id=human,
                    customer_id=outsider,
                    lease_id=lease,
                    period_start=date(2026, 8, 1),
                )
        assert invalid.value.sqlstate == "23514"
        assert history(connection) == before_invalid
        obligation = uuid4()
        connection.execute(
            "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,"
            "category,description,authorized_amount_usd_cents,governing_due_date,"
            "due_date_source,source_reference,authorized_at,authorized_by,authorization_reference) "
            "VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','Approved synthetic signer obligation',"
            "7500,current_date+1,'approved-signer-source','approved-signer-source',"
            "statement_timestamp(),%s,'invoice.nonrecurring.authorize')",
            (obligation, other, lease, human),
        )
    writer = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    actor = invoice_api_actor(human, prop)
    command = CreateInvoiceDraftCommand(uuid4(), obligation)
    created = writer.create_draft(prop, command, actor=actor)
    invoice = UUID(str(created["id"]))
    current = created
    if issued:
        current = writer.issue(
            prop, invoice, IssueInvoiceCommand(uuid4(), int(str(created["version"]))), actor=actor
        )
    terminate(migrated_database_url, human, prop, lease, date(2026, 7, 10))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    with psycopg.connect(migrated_database_url) as connection:
        before_read = history(connection)
    first = read.page(lease, actor=reader(human, prop), limit=1)
    assert first.next_cursor is not None and first.primary_tenant_id == primary
    second = read.page(lease, actor=reader(human, prop), limit=1, after_line_id=first.next_cursor)
    assert second.next_cursor is None and second.primary_tenant_id == primary
    assert {row.invoice_id: row.customer_id for row in first.items + second.items} == {
        rent_invoice: primary,
        invoice: other,
    }
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == before_read
    wrong = uuid4()
    with pytest.raises(TerminationInvoiceNotFoundError):
        PostgresTerminationInvoiceReadService(runtime_database_url(), wrong).page(
            lease, actor=reader(human, wrong)
        )
    assert writer.create_draft(prop, command, actor=actor) == created
    writer.void(
        prop,
        invoice,
        VoidInvoiceCommand(
            uuid4(), "Approved original-source correction", int(str(current["version"]))
        ),
        actor=actor,
    )
    history_row = next(
        row
        for row in read.page(lease, actor=reader(human, prop)).items
        if row.invoice_id == invoice
    )
    assert history_row.customer_id == other and history_row.invoice_status == "VOID"
    assert history_row.issued is issued and history_row.components == ()


def test_partial_mixed_invoice_pages_accept_fully_applied_rent_and_unpaid_service(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, occupancy = setup_billing_source(connection)
    generated = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy), actor=authenticated(human, prop)
    )
    assert generated.invoice_id is not None
    terminate(migrated_database_url, human, prop, lease, date(2026, 8, 10))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    original = read.page(lease, actor=reader(human, prop))
    rent = next(row for row in original.items if row.category == "RENT")
    with psycopg.connect(migrated_database_url) as connection:
        paid = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=rent.outstanding_usd_cents,
        )
    payments().post(
        prop,
        paid,
        payment_designated(generated.invoice_id, rent.invoice_line_id, rent.outstanding_usd_cents),
        actor=payment_actor(human, prop),
    )
    rows: list[TerminationInvoiceLine] = []
    cursor = None
    while True:
        page = read.page(lease, actor=reader(human, prop), limit=1, after_line_id=cursor)
        rows.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        assert len(rows) < len(original.items)
    assert len(rows) == len(original.items) and len(rows) > 1
    assert all(row.invoice_status == "PARTIALLY_PAID" for row in rows)
    paid_rent = next(row for row in rows if row.category == "RENT")
    assert paid_rent.outstanding_usd_cents == 0
    services = [row for row in rows if row.category == "SERVICE_CHARGES"]
    assert services and all(row.outstanding_usd_cents > 0 for row in services)


def original_correction_source(
    connection: Connection[tuple[object, ...]], invoice: UUID, lease: UUID
) -> tuple[object, ...]:
    """Original financial sources, including every component and signed Lease field."""
    header = connection.execute(
        "SELECT to_jsonb(i)-ARRAY['status','version','updated_at','updated_by'] "
        "FROM app.invoices i WHERE id=%s",
        (invoice,),
    ).fetchone()
    lines = connection.execute(
        "SELECT to_jsonb(l) FROM app.invoice_lines l WHERE invoice_id=%s ORDER BY id",
        (invoice,),
    ).fetchall()
    components = connection.execute(
        "SELECT to_jsonb(c) FROM app.invoice_line_calculation_components c "
        "JOIN app.invoice_lines l ON l.id=c.invoice_line_id WHERE l.invoice_id=%s ORDER BY c.id",
        (invoice,),
    ).fetchall()
    signed = connection.execute(
        "SELECT to_jsonb(l) FROM app.leases l WHERE id=%s", (lease,)
    ).fetchone()
    return header, lines, components, signed


def test_termination_initial_credit_adjustment_preserves_sources_and_concurrent_replay(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, lease, occupancy = setup_billing_source(connection)
    billing = PostgresRentBillingService(financial_database_url(), prop, human)
    initial = initial_command(lease, occupancy)
    generated = billing.generate(initial, actor=authenticated(human, prop))
    event = terminate(migrated_database_url, human, prop, lease, date(2026, 7, 28))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    page = read.page(lease, actor=reader(human, prop))
    rent = next(row for row in page.items if row.category == "RENT")
    assert page.termination_event_id == event
    assert rent.original_usd_cents == 92903 and page.full_final_month_rent_usd_cents == 80000
    assert rent.original_rent_coverage is OriginalRentCoverage.FINAL_AND_LATER_MONTHS
    services = [row for row in page.items if row.category == "SERVICE_CHARGES"]
    with psycopg.connect(migrated_database_url) as connection:
        original = original_correction_source(connection, rent.invoice_id, lease)
    request = AdjustInvoiceCommand(
        uuid4(),
        rent.invoice_line_id,
        AdjustmentType.CREDIT,
        12903,
        f"approved-termination/{event}",
        "Approved final July Rent; remove net excess from initial advance billing",
        rent.invoice_version,
    )
    staff = invoice_api_actor(human, prop)
    flow = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    barrier = Barrier(2)

    def apply_once() -> dict[str, object]:
        barrier.wait(timeout=10)
        return PostgresInvoiceService(runtime_database_url(), financial_database_url()).adjust(
            prop,
            rent.invoice_id,
            request,
            actor=staff,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [
            future.result(timeout=20)
            for future in (pool.submit(apply_once), pool.submit(apply_once))
        ]
    assert first == second == flow.adjust(prop, rent.invoice_id, request, actor=staff)
    changed = read.page(lease, actor=reader(human, prop))
    current = next(row for row in changed.items if row.category == "RENT")
    assert (
        current.original_usd_cents,
        current.adjusted_usd_cents,
        current.outstanding_usd_cents,
    ) == (92903, 80000, 80000)
    assert [
        (x.invoice_line_id, x.original_usd_cents, x.adjusted_usd_cents, x.components)
        for x in changed.items
        if x.category == "SERVICE_CHARGES"
    ] == [
        (x.invoice_line_id, x.original_usd_cents, x.adjusted_usd_cents, x.components)
        for x in services
    ]
    assert changed.financial_completion_assessed is False
    assert billing.generate(initial, actor=authenticated(human, prop)) == generated
    with psycopg.connect(migrated_database_url) as connection:
        assert original_correction_source(connection, rent.invoice_id, lease) == original
        assert connection.execute(
            "SELECT a.amount_usd_cents,a.source_reference,a.actor_id,count(e.id) "
            "FROM app.invoice_adjustments a JOIN app.audit_events e "
            "ON e.linked_source_event_id=a.id "
            "AND e.action='invoice.adjusted' AND e.entity_id=a.invoice_id "
            "AND e.actor_id=a.actor_id "
            "WHERE a.invoice_id=%s GROUP BY a.id",
            (rent.invoice_id,),
        ).fetchall() == [(12903, request.source_reference, human, 1)]
        assert connection.execute(
            "SELECT count(*) FROM app.invoice_commands WHERE invoice_id=%s AND action='adjust'",
            (rent.invoice_id,),
        ).fetchone() == (1,)
        unchanged = history(connection)
    with pytest.raises(InvoiceIdempotencyKeyReused):
        flow.adjust(
            prop, rent.invoice_id, replace(request, reason="Changed approved reason"), actor=staff
        )
    with pytest.raises(InvoiceInvalidError):
        flow.void(
            prop,
            rent.invoice_id,
            VoidInvoiceCommand(uuid4(), "Must retain active Adjustment", current.invoice_version),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == unchanged


def test_termination_future_void_requires_separate_payment_and_credit_reversals(
    migrated_database_url: str,
) -> None:
    human, prop, credit, invoice, line, _ = source_with_prior_credit(
        migrated_database_url, amount=20000, period_start=date(2026, 8, 1)
    )
    with psycopg.connect(migrated_database_url) as connection:
        identity = connection.execute(
            "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert identity is not None
        customer, lease = identity
        assert isinstance(customer, UUID) and isinstance(lease, UUID)
        paid = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=20000
        )
    terminate(migrated_database_url, human, prop, lease, date(2026, 7, 10))
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    old = read.page(lease, actor=reader(human, prop)).items[0]
    assert old.original_rent_coverage is OriginalRentCoverage.LATER_MONTHS
    posted = payments().post(
        prop, paid, payment_designated(invoice, line, 10000), actor=payment_actor(human, prop)
    )
    applied = credits().apply(
        prop,
        credit,
        credit_designated(invoice, line, 10000),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    flow = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    staff = invoice_api_actor(human, prop)
    current = read.page(lease, actor=reader(human, prop)).items[0]
    assert current.invoice_version != old.invoice_version
    with psycopg.connect(migrated_database_url) as connection:
        original = original_correction_source(connection, invoice, lease)
        unchanged = history(connection)
    with pytest.raises(InvoiceVersionConflict):
        flow.void(
            prop,
            invoice,
            VoidInvoiceCommand(
                uuid4(), "Approved invalid August advance Rent", old.invoice_version
            ),
            actor=staff,
        )
    with pytest.raises(InvoiceInvalidError):
        flow.void(
            prop,
            invoice,
            VoidInvoiceCommand(
                uuid4(), "Approved invalid August advance Rent", current.invoice_version
            ),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        obligation = connection.execute(
            "SELECT app.invoice_adjusted_line_obligation(%s)", (line,)
        ).fetchone()
        assert obligation is not None
    # BR-INV-044 replaced the older rule: a credit beyond the unpaid amount is accepted and
    # its excess becomes Customer Credit (see test_credit_adjustment_excess_migration.py).
    # Still rejected: a credit beyond the line's adjusted obligation.
    with pytest.raises(InvoiceInvalidError):
        flow.adjust(
            prop,
            invoice,
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.CREDIT,
                int(str(obligation[0])) + 1,
                "approved/termination",
                "Applications require explicit resolution",
                current.invoice_version,
            ),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == unchanged
    ids = posted["allocation_ids"]
    assert isinstance(ids, list) and len(ids) == 1
    allocation = UUID(str(ids[0]))
    payments().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Approved invalid future-month attribution"),
        actor=payment_actor(human, prop),
    )
    current = read.page(lease, actor=reader(human, prop)).items[0]
    with psycopg.connect(migrated_database_url) as connection:
        unchanged = history(connection)
    with pytest.raises(InvoiceInvalidError):
        flow.void(
            prop,
            invoice,
            VoidInvoiceCommand(
                uuid4(), "Credit still requires explicit reversal", current.invoice_version
            ),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == unchanged
    credits().reverse_application(
        prop,
        application_id(applied),
        ReverseCreditApplicationCommand(uuid4(), "Approved invalid future-month attribution"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    current = read.page(lease, actor=reader(human, prop)).items[0]
    request = VoidInvoiceCommand(
        uuid4(), "Approved Invoice wholly beyond July termination", current.invoice_version
    )
    with psycopg.connect(migrated_database_url) as connection:
        before_void = history(connection)
        position = connection.execute(
            "SELECT app.payment_available_value(%s),app.credit_available_value(%s)", (paid, credit)
        ).fetchone()
    voided = flow.void(prop, invoice, request, actor=staff)
    assert flow.void(prop, invoice, request, actor=staff) == voided
    with psycopg.connect(migrated_database_url) as connection:
        assert original_correction_source(connection, invoice, lease) == original
        after_void = history(connection)
        for table in (
            "payments",
            "payment_allocations",
            "payment_allocation_reversals",
            "customer_credits",
            "customer_credit_applications",
            "customer_credit_application_reversals",
            "refunds",
        ):
            assert after_void[table] == before_void[table]
        assert (
            connection.execute(
                "SELECT app.payment_available_value(%s),app.credit_available_value(%s)",
                (paid, credit),
            ).fetchone()
            == position
            == (20000, 20000)
        )
        assert connection.execute(
            "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", (invoice,)
        ).fetchone() == (1,)
    final = read.page(lease, actor=reader(human, prop)).items[0]
    assert (
        final.invoice_status == "VOID"
        and final.original_usd_cents == 80000
        and final.outstanding_usd_cents == 0
    )


def test_termination_credit_adjustment_does_not_create_void_or_financial_closure(
    migrated_database_url: str,
) -> None:
    human, prop, _, lease, invoices = source(migrated_database_url, months=(8,))
    invoice, line = invoices[0]
    read = PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
    current = read.page(lease, actor=reader(human, prop)).items[0]
    flow = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    request = AdjustInvoiceCommand(
        uuid4(),
        line,
        AdjustmentType.CREDIT,
        80000,
        "approved/future-period-correction",
        "Approved linked correction of invalid August obligation",
        current.invoice_version,
    )
    with psycopg.connect(migrated_database_url) as connection:
        original = original_correction_source(connection, invoice, lease)
    result = flow.adjust(prop, invoice, request, actor=invoice_api_actor(human, prop))
    assert flow.adjust(prop, invoice, request, actor=invoice_api_actor(human, prop)) == result
    page = read.page(lease, actor=reader(human, prop))
    current = page.items[0]
    assert (
        current.invoice_status,
        current.original_usd_cents,
        current.adjusted_usd_cents,
        current.outstanding_usd_cents,
    ) == ("PAID", 80000, 0, 0)
    assert current.active_adjustment_count == 1 and page.financial_completion_assessed is False
    with psycopg.connect(migrated_database_url) as connection:
        assert original_correction_source(connection, invoice, lease) == original
        assert connection.execute(
            "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", (invoice,)
        ).fetchone() == (0,)


def test_termination_invoice_corrections_enforce_property_and_capability_before_effects(
    migrated_database_url: str,
) -> None:
    human, prop, _, lease, invoices = source(migrated_database_url, months=(8,))
    invoice, line = invoices[0]
    current = (
        PostgresTerminationInvoiceReadService(runtime_database_url(), prop)
        .page(lease, actor=reader(human, prop))
        .items[0]
    )
    flow = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    request = AdjustInvoiceCommand(
        uuid4(),
        line,
        AdjustmentType.CREDIT,
        100,
        "approved/termination",
        "Authorized adjustment only",
        current.invoice_version,
    )
    void = VoidInvoiceCommand(
        uuid4(), "Authorized invalid advance Invoice only", current.invoice_version
    )
    with psycopg.connect(migrated_database_url) as connection:
        unchanged = history(connection)
    with pytest.raises(InvoiceAuthorizationError):
        flow.adjust(prop, invoice, request, actor=reader(human, prop))
    with pytest.raises(InvoiceAuthorizationError):
        flow.void(prop, invoice, void, actor=reader(human, prop))
    with pytest.raises(InvoiceAuthorizationError):
        flow.adjust(uuid4(), invoice, request, actor=invoice_api_actor(human, prop))
    with pytest.raises(InvoiceAuthorizationError):
        flow.void(uuid4(), invoice, void, actor=invoice_api_actor(human, prop))
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection) == unchanged
