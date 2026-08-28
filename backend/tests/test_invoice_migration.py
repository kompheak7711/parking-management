"""Real PostgreSQL coverage for V1-039 Invoice and billing-run persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.types.json import Jsonb

from test_lease_migration import create_draft, setup_sources, sign_lease


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Apply the complete forward migration chain to disposable PostgreSQL."""
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    """Provide an isolated migration-owner transaction."""
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def bootstrap_database_url() -> str:
    value = os.environ.get("BOOTSTRAP_DATABASE_URL")
    if value is None:
        pytest.skip("BOOTSTRAP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def register_billing_service_principal(
    connection: Connection[tuple[object, ...]], *, property_id: UUID, created_by: UUID
) -> UUID:
    """Register one active Property-scoped billing service identity."""
    actor_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_service_principals("
        "actor_id,property_id,capability,lifecycle_state,created_by) "
        "VALUES (%s,%s,'billing.generate','active',%s)",
        (actor_id, property_id, created_by),
    )
    return actor_id


def set_draft_correction_context(
    connection: Connection[tuple[object, ...]], *, actor_id: UUID, reason: str
) -> None:
    """Supply the explicit actor and reason required for one DRAFT correction transaction."""
    connection.execute(
        "SELECT set_config('app.draft_correction_actor_id',%s,true),"
        "set_config('app.draft_correction_reason',%s,true)",
        (str(actor_id), reason),
    )


def create_recurring_rent_invoice(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    customer_id: UUID,
    lease_id: UUID,
    period_start: date = date(2027, 2, 1),
    create_line: bool = True,
    issue: bool = True,
    originating_billing_run_attempt_id: UUID | None = None,
    line_created_at: datetime | None = None,
    line_actor_id: UUID | None = None,
    due_date_source: str = "BR-RENT-018",
    validate_immediately: bool = True,
) -> tuple[UUID, UUID]:
    """Create the exact relational shape for one recurring Rent Invoice."""
    if (
        connection.execute(
            "SELECT 1 FROM app.occupancies WHERE lease_id=%s LIMIT 1", (lease_id,)
        ).fetchone()
        is None
    ):
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
            "created_by,updated_by) SELECT %s,lease.id,%s,lease.start_date,"
            "lease.created_by,lease.created_by FROM app.leases AS lease WHERE lease.id=%s",
            (uuid4(), customer_id, lease_id),
        )
    invoice_date = period_start
    generated_started_at: datetime | None = None
    if originating_billing_run_attempt_id is not None:
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        generated_context = connection.execute(
            "SELECT run.business_date,attempt.started_at,run.system_actor_id "
            "FROM app.billing_run_attempts AS attempt "
            "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id "
            "WHERE attempt.id=%s",
            (originating_billing_run_attempt_id,),
        ).fetchone()
        assert generated_context is not None
        stored_invoice_date, stored_started_at, stored_actor_id = generated_context
        assert isinstance(stored_invoice_date, date)
        assert isinstance(stored_started_at, datetime)
        assert isinstance(stored_actor_id, UUID)
        invoice_date = stored_invoice_date
        generated_started_at = stored_started_at
        actor_id = stored_actor_id
    period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
        days=1
    )
    invoice_id = uuid4()
    line_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.invoices(
            id,invoice_number,customer_id,lease_id,primary_category,status,
            invoice_date,due_date,billing_period_start,billing_period_end,
            rent_billing_kind,original_total_usd_cents,due_date_rule,due_date_source,
            created_at,created_by,updated_at,updated_by,originating_billing_run_attempt_id
        ) VALUES (%s,%s,%s,%s,'RENT','DRAFT',%s,%s,%s,%s,'RECURRING',80000,
            'RECURRING_RENT_FIFTH',%s,COALESCE(%s,statement_timestamp()),%s,
            COALESCE(%s,statement_timestamp()),%s,%s)
        """,
        (
            invoice_id,
            f"INV-{invoice_id.hex}",
            customer_id,
            lease_id,
            invoice_date,
            period_start + timedelta(days=4),
            period_start,
            period_end,
            due_date_source,
            generated_started_at,
            actor_id,
            generated_started_at,
            actor_id,
            originating_billing_run_attempt_id,
        ),
    )
    if not create_line:
        return invoice_id, line_id
    connection.execute(
        """
        INSERT INTO app.invoice_lines(
            id,invoice_id,line_sequence,category,description,amount_usd_cents,
            period_start,period_end,source_lease_id,contractual_monthly_usd_cents,
            billable_days,calendar_days,calculation_trace,created_at,created_by
        ) VALUES (%s,%s,1,'RENT','Monthly Rent',80000,%s,%s,%s,80000,%s,%s,%s,
            COALESCE(%s::timestamptz,%s::timestamptz,statement_timestamp()),%s)
        """,
        (
            line_id,
            invoice_id,
            period_start,
            period_end,
            lease_id,
            period_end.day,
            period_end.day,
            Jsonb({"formula": "monthly_rent", "amount_usd_cents": 80000}),
            line_created_at,
            generated_started_at,
            line_actor_id or actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.invoice_line_calculation_components(
            id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
            contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,
            calculation_trace,created_by
        ) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',%s,%s,80000,%s,%s,80000,%s,%s)
        """,
        (
            uuid4(),
            line_id,
            period_start,
            period_end,
            period_end.day,
            period_end.day,
            Jsonb({"formula": "monthly_rent", "amount_usd_cents": 80000}),
            actor_id,
        ),
    )
    if issue:
        connection.execute(
            """
            UPDATE app.invoices SET status='UNPAID',
                issued_at=GREATEST(statement_timestamp(),COALESCE(%s,statement_timestamp())),
                issued_by=%s,version=2,
                updated_at=GREATEST(statement_timestamp(),COALESCE(%s,statement_timestamp())),
                updated_by=%s
            WHERE id=%s
            """,
            (generated_started_at, actor_id, generated_started_at, actor_id, invoice_id),
        )
        if originating_billing_run_attempt_id is None and validate_immediately:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return invoice_id, line_id


def setup_signed_lease(
    connection: Connection[tuple[object, ...]],
    *,
    start_date: date = date(2027, 1, 1),
    end_date: date = date(2027, 12, 31),
    with_occupancy: bool = True,
) -> tuple[UUID, UUID, UUID, UUID]:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
    )
    sign_lease(connection, lease_id, actor_id)
    if with_occupancy:
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
            "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (uuid4(), lease_id, tenant_id, start_date, actor_id, actor_id),
        )
    return actor_id, property_id, tenant_id, lease_id


def test_terminated_lease_can_preserve_full_voluntary_final_month_rent(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    prior_month_end = date.today().replace(day=1) - timedelta(days=1)
    period_start = prior_month_end.replace(day=1)
    termination_date = period_start.replace(day=min(15, prior_month_end.day))

    def issue_final_service_month(
        *,
        service_property_id: UUID,
        service_lease_id: UUID,
        service_customer_id: UUID,
        service_actor_id: UUID,
        due_date_source: str = "BR-SVC-013",
    ) -> UUID:
        service_id = uuid4()
        rate_id = uuid4()
        approval_id = uuid4()
        term_id = uuid4()
        invoice_id = uuid4()
        line_id = uuid4()
        calendar_days = prior_month_end.day
        connection.execute(
            "INSERT INTO app.property_services(id,property_id,service_code,display_name,"
            "configured_by,created_by,updated_by) VALUES (%s,%s,%s,'Trash Collection',"
            "%s,%s,%s)",
            (
                service_id,
                service_property_id,
                f"FINAL-{service_id.hex}",
                service_actor_id,
                service_actor_id,
                service_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
            "effective_date,occurred_at,actor_id) VALUES (%s,%s,10000,%s,now(),%s)",
            (rate_id, service_id, period_start, service_actor_id),
        )
        connection.execute(
            "INSERT INTO app.property_service_approval_periods(id,property_service_id,"
            "effective_from,effective_through,approval_reference,approved_at,approved_by,"
            "reason) VALUES (%s,%s,%s,%s,'owner-final-service',now(),%s,"
            "'Approved final Service period')",
            (approval_id, service_id, period_start, prior_month_end, service_actor_id),
        )
        connection.execute(
            "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,"
            "applicable_from,applicable_through,service_approval_period_id,terms_reference,"
            "recorded_at,recorded_by) VALUES (%s,%s,%s,%s,%s,%s,'signed-final-service',"
            "now(),%s)",
            (
                term_id,
                service_lease_id,
                service_id,
                period_start,
                prior_month_end,
                approval_id,
                service_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,"
            "status,invoice_date,due_date,billing_period_start,billing_period_end,"
            "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by) "
            "VALUES (%s,%s,%s,%s,'SERVICE_CHARGES','DRAFT',%s,%s,%s,%s,10000,"
            "'GOVERNING_SOURCE',%s,%s,%s)",
            (
                invoice_id,
                f"INV-{invoice_id.hex}",
                service_customer_id,
                service_lease_id,
                prior_month_end,
                prior_month_end,
                period_start,
                prior_month_end,
                due_date_source,
                service_actor_id,
                service_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
            "amount_usd_cents,period_start,period_end,source_lease_id,property_service_id,"
            "service_rate_id,lease_service_term_id,service_approval_period_id,"
            "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,"
            "created_by) VALUES (%s,%s,1,'SERVICE_CHARGES','Trash Collection',10000,%s,%s,"
            "%s,%s,%s,%s,%s,10000,%s,%s,%s,%s)",
            (
                line_id,
                invoice_id,
                period_start,
                prior_month_end,
                service_lease_id,
                service_id,
                rate_id,
                term_id,
                approval_id,
                calendar_days,
                calendar_days,
                Jsonb({"formula": "full_final_service_month"}),
                service_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
            "component_sequence,component_kind,period_start,period_end,service_rate_id,"
            "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
            "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',%s,%s,"
            "%s,10000,%s,%s,10000,%s,%s)",
            (
                uuid4(),
                line_id,
                period_start,
                prior_month_end,
                rate_id,
                calendar_days,
                calendar_days,
                Jsonb({"formula": "full_final_service_month"}),
                service_actor_id,
            ),
        )
        connection.execute(
            "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
            "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (service_actor_id, service_actor_id, invoice_id),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return invoice_id

    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=(period_start - timedelta(days=1)).replace(day=1),
        end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
    )
    sign_lease(connection, lease_id, actor_id)
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            lease_id,
            tenant_id,
            (period_start - timedelta(days=1)).replace(day=1),
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "SELECT app.terminate_lease(%s,%s,%s,%s,%s,2,%s,statement_timestamp(),"
        "'BR-LEASE-021','Processed voluntary departure',%s)",
        (
            property_id,
            uuid4(),
            "a" * 64,
            uuid4(),
            lease_id,
            termination_date,
            actor_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=period_start,
        due_date_source="BR-RENT-024",
    )
    assert connection.execute(
        "SELECT status,billing_period_start,billing_period_end FROM app.invoices WHERE id=%s",
        (invoice_id,),
    ).fetchone() == ("UNPAID", period_start, prior_month_end)
    voluntary_service_invoice_id = issue_final_service_month(
        service_property_id=property_id,
        service_lease_id=lease_id,
        service_customer_id=tenant_id,
        service_actor_id=actor_id,
    )
    assert connection.execute(
        "SELECT status,billing_period_start,billing_period_end FROM app.invoices WHERE id=%s",
        (voluntary_service_invoice_id,),
    ).fetchone() == ("UNPAID", period_start, prior_month_end)
    with pytest.raises(Error) as voluntary_service_requires_authoritative_source:
        with connection.transaction():
            issue_final_service_month(
                service_property_id=property_id,
                service_lease_id=lease_id,
                service_customer_id=tenant_id,
                service_actor_id=actor_id,
                due_date_source="unrelated-voluntary-service-policy",
            )
    assert voluntary_service_requires_authoritative_source.value.sqlstate == "23514"

    other_actor_id, other_property_id, other_unit_id, other_tenant_id, _ = setup_sources(connection)
    other_lease_id = create_draft(
        connection,
        actor_id=other_actor_id,
        unit_id=other_unit_id,
        primary_tenant_id=other_tenant_id,
        start_date=(period_start - timedelta(days=1)).replace(day=1),
        end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
    )
    sign_lease(connection, other_lease_id, other_actor_id)
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            other_lease_id,
            other_tenant_id,
            (period_start - timedelta(days=1)).replace(day=1),
            other_actor_id,
            other_actor_id,
        ),
    )
    connection.execute(
        "SELECT app.terminate_lease(%s,%s,%s,%s,%s,2,%s,statement_timestamp(),"
        "'lease.violation.termination','Processed involuntary termination',%s)",
        (
            other_property_id,
            uuid4(),
            "b" * 64,
            uuid4(),
            other_lease_id,
            termination_date,
            other_actor_id,
        ),
    )
    with pytest.raises(Error) as involuntary_full_month:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=other_actor_id,
                customer_id=other_tenant_id,
                lease_id=other_lease_id,
                period_start=period_start,
                due_date_source="BR-RENT-024",
            )
    assert involuntary_full_month.value.sqlstate == "23514"
    with pytest.raises(Error) as involuntary_full_service_month:
        with connection.transaction():
            issue_final_service_month(
                service_property_id=other_property_id,
                service_lease_id=other_lease_id,
                service_customer_id=other_tenant_id,
                service_actor_id=other_actor_id,
            )
    assert involuntary_full_service_month.value.sqlstate == "23514"


def test_issued_invoice_can_be_voided_after_later_involuntary_lease_termination(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    period_start = date.today().replace(day=1)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=(period_start - timedelta(days=1)).replace(day=1),
        end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
    )
    sign_lease(connection, lease_id, actor_id)
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            lease_id,
            tenant_id,
            (period_start - timedelta(days=1)).replace(day=1),
            actor_id,
            actor_id,
        ),
    )
    invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=period_start,
        validate_immediately=False,
    )
    connection.execute(
        "SELECT app.terminate_lease(%s,%s,%s,%s,%s,2,current_date,statement_timestamp(),"
        "'lease.violation.termination','Later involuntary termination',%s)",
        (property_id, uuid4(), "c" * 64, uuid4(), lease_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    voided_at = datetime.now(UTC) + timedelta(seconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (voided_at, actor_id, invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Invalidated after later Lease termination',"
        "%s,%s,'invoice.void')",
        (uuid4(), invoice_id, voided_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status,issued_at IS NOT NULL FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone() == ("VOID", True)


def test_invoice_tables_are_current_forward_only_and_read_only_to_runtime(
    migrated_database_url: str,
) -> None:
    obligation_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260828_30",
        )
        expected = {
            "actor_identities",
            "billing_service_principals",
            "invoices",
            "invoice_lines",
            "active_invoice_source_claims",
            "invoice_serialization_guards",
            "invoice_adjustments",
            "invoice_void_events",
            "authorized_nonrecurring_obligations",
            "invoice_line_calculation_components",
            "invoice_draft_revision_events",
            "late_payment_decisions",
            "late_payment_charges",
            "late_payment_charge_corrections",
            "invoice_adjustment_reversals",
            "billing_runs",
            "billing_run_eligible_sources",
            "billing_run_attempts",
            "billing_run_items",
        }
        actual = {
            row[0]
            for row in owner.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='app'"
            ).fetchall()
        }
        assert expected <= actual
        trigger_names = [
            row[0]
            for row in owner.execute(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid='app.invoice_lines'::regclass AND NOT tgisinternal "
                "ORDER BY tgname"
            ).fetchall()
        ]
        assert trigger_names.index("invoice_lines_00_serialize_source") < trigger_names.index(
            "invoice_lines_10_protect_history"
        )
        item_guard_row = owner.execute(
            "SELECT pg_get_functiondef('app.protect_billing_run_item_history()'::regprocedure)"
        ).fetchone()
        assert item_guard_row is not None
        item_guard = str(item_guard_row[0])
        assert item_guard.index("FROM app.billing_run_attempts") < item_guard.index(
            "FROM app.billing_runs WHERE"
        )

        actor_id, _, _, customer_id, _ = setup_sources(owner)
        owner.execute(
            "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
            "description,authorized_amount_usd_cents,governing_due_date,due_date_source,"
            "source_reference,authorized_at,authorized_by,authorization_reference) VALUES "
            "(%s,%s,'MISCELLANEOUS_CHARGES','Forward-only evidence',100,current_date+1,"
            "'forward-only-test','forward-only-test',statement_timestamp(),%s,"
            "'invoice.nonrecurring.authorize')",
            (obligation_id, customer_id, actor_id),
        )
        owner.commit()

        for role, expected_select in (
            ("prm_runtime", True),
            ("prm_financial", True),
            ("prm_bootstrap", False),
        ):
            for table in expected:
                relation = f"app.{table}"
                assert owner.execute(
                    "SELECT has_table_privilege(%s,%s,'SELECT')", (role, relation)
                ).fetchone() == (expected_select and table != "invoice_serialization_guards",)
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert owner.execute(
                        "SELECT has_table_privilege(%s,%s,%s)",
                        (role, relation, privilege),
                    ).fetchone() == (False,)

    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260826_28")
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260828_30",
        )
        assert owner.execute(
            "SELECT description FROM app.authorized_nonrecurring_obligations WHERE id=%s",
            (obligation_id,),
        ).fetchone() == ("Forward-only evidence",)

    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as restricted:
            assert restricted.execute("SELECT count(*) FROM app.invoices").fetchone() is not None
            with pytest.raises(Error) as direct_mutation:
                restricted.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,idempotency_key,system_actor_id,status,started_at) "
                    "VALUES (%s,%s,'RENT','forbidden',current_date,%s,%s,'RUNNING',now())",
                    (uuid4(), uuid4(), uuid4(), uuid4()),
                )
            assert direct_mutation.value.sqlstate == "42501"

    with psycopg.connect(bootstrap_database_url()) as bootstrap:
        with pytest.raises(Error) as bootstrap_read:
            bootstrap.execute("SELECT count(*) FROM app.invoices")
        assert bootstrap_read.value.sqlstate == "42501"


def test_initial_rent_component_kinds_are_bound_to_calendar_position(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, tenant_id, lease_id = setup_signed_lease(
        connection, with_occupancy=False
    )
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct Initial Rent component evidence"
    )
    move_in_date = date(2027, 1, 21)
    occupancy_id = uuid4()
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (occupancy_id, lease_id, tenant_id, move_in_date, actor_id, actor_id),
    )
    invoice_id = uuid4()
    line_id = uuid4()
    prorated_amount = round(80000 * 11 / 31)
    total_amount = prorated_amount + 80000
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,due_date,billing_period_start,billing_period_end,rent_billing_kind,"
        "source_occupancy_id,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by) VALUES "
        "(%s,%s,%s,%s,'RENT','DRAFT',%s,%s,%s,'2027-02-28','INITIAL',%s,%s,"
        "'INITIAL_RENT_SEVEN_DAYS','BR-RENT-017',%s,%s)",
        (
            invoice_id,
            f"INV-{invoice_id.hex}",
            tenant_id,
            lease_id,
            move_in_date,
            move_in_date + timedelta(days=7),
            move_in_date,
            occupancy_id,
            total_amount,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,period_start,period_end,source_lease_id,"
        "contractual_monthly_usd_cents,calculation_trace,created_by) VALUES "
        "(%s,%s,1,'RENT','Initial Rent',%s,%s,'2027-02-28',%s,80000,%s,%s)",
        (
            line_id,
            invoice_id,
            total_amount,
            move_in_date,
            lease_id,
            Jsonb({"formula": "initial_rent"}),
            actor_id,
        ),
    )
    first_component_id = uuid4()
    second_component_id = uuid4()
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,"
        "contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES "
        "(%s,%s,1,'PRORATED_MOVE_IN_MONTH','2027-01-21','2027-01-31',80000,11,31,%s,%s,%s),"
        "(%s,%s,2,'PRORATED_MOVE_IN_MONTH','2027-02-01','2027-02-28',80000,28,28,80000,"
        "%s,%s)",
        (
            first_component_id,
            line_id,
            prorated_amount,
            Jsonb({"formula": "prorated_move_in"}),
            actor_id,
            second_component_id,
            line_id,
            Jsonb({"formula": "full_following"}),
            actor_id,
        ),
    )
    with pytest.raises(Error) as duplicate_move_in_label:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert duplicate_move_in_label.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_line_calculation_components "
        "SET component_kind='FULL_FOLLOWING_MONTH' WHERE id=%s",
        (second_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=3 WHERE id=%s",
        (second_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=2 WHERE id=%s",
        (first_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=1 WHERE id=%s",
        (second_component_id,),
    )
    with pytest.raises(Error) as reversed_component_sequence:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert reversed_component_sequence.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=3 WHERE id=%s",
        (second_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=1 WHERE id=%s",
        (first_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET component_sequence=2 WHERE id=%s",
        (second_component_id,),
    )
    connection.execute(
        "UPDATE app.invoice_lines SET billable_days=11,calendar_days=31 WHERE id=%s",
        (line_id,),
    )
    with pytest.raises(Error) as ambiguous_two_component_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert ambiguous_two_component_snapshot.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_lines SET billable_days=NULL,calendar_days=NULL WHERE id=%s",
        (line_id,),
    )
    service_id = uuid4()
    service_rate_id = uuid4()
    service_approval_id = uuid4()
    service_term_id = uuid4()
    service_line_id = uuid4()
    service_first_component_id = uuid4()
    service_second_component_id = uuid4()
    prorated_service_amount = round(10000 * 11 / 31)
    service_total_amount = prorated_service_amount + 10000
    connection.execute(
        "INSERT INTO app.property_services(id,property_id,service_code,display_name,configured_by,"
        "created_by,updated_by) VALUES (%s,%s,%s,'Initial Service',%s,%s,%s)",
        (
            service_id,
            property_id,
            f"INITIAL-{service_id.hex}",
            actor_id,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,occurred_at,actor_id) VALUES (%s,%s,10000,'2027-01-01',now(),%s)",
        (service_rate_id, service_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.property_service_approval_periods(id,property_service_id,effective_from,"
        "effective_through,approval_reference,approved_at,approved_by,reason) VALUES "
        "(%s,%s,'2027-01-01','2027-02-28','initial-service-approval',now(),%s,"
        "'Approved Initial service period')",
        (service_approval_id, service_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,applicable_from,"
        "applicable_through,service_approval_period_id,terms_reference,recorded_at,recorded_by) "
        "VALUES (%s,%s,%s,'2027-01-01','2027-02-28',%s,'signed-initial-service',now(),%s)",
        (service_term_id, lease_id, service_id, service_approval_id, actor_id),
    )
    connection.execute(
        "UPDATE app.invoices SET original_total_usd_cents=%s,version=2,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (total_amount + service_total_amount, actor_id, invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,period_start,period_end,source_lease_id,property_service_id,"
        "service_rate_id,lease_service_term_id,service_approval_period_id,"
        "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,created_by) "
        "VALUES (%s,%s,2,'SERVICE_CHARGES','Initial service',%s,'2027-01-21',"
        "'2027-02-28',%s,%s,%s,%s,%s,10000,NULL,NULL,%s,%s)",
        (
            service_line_id,
            invoice_id,
            service_total_amount,
            lease_id,
            service_id,
            service_rate_id,
            service_term_id,
            service_approval_id,
            Jsonb({"formula": "full_following_service"}),
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,service_rate_id,"
        "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,1,'PRORATED_MOVE_IN_MONTH',"
        "'2027-01-21','2027-01-31',%s,10000,11,31,%s,%s,%s)",
        (
            service_first_component_id,
            service_line_id,
            service_rate_id,
            prorated_service_amount,
            Jsonb({"formula": "full_following_service"}),
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,service_rate_id,"
        "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,2,'PRORATED_MOVE_IN_MONTH',"
        "'2027-02-01','2027-02-28',%s,10000,28,28,10000,%s,%s)",
        (
            service_second_component_id,
            service_line_id,
            service_rate_id,
            Jsonb({"formula": "full_following_service"}),
            actor_id,
        ),
    )
    with pytest.raises(Error) as mislabeled_following_month_service:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mislabeled_following_month_service.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_line_calculation_components "
        "SET component_kind='FULL_FOLLOWING_MONTH' WHERE id=%s",
        (service_second_component_id,),
    )
    with pytest.raises(RuntimeError, match="rollback valid common-rate probe"):
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            raise RuntimeError("rollback valid common-rate probe")

    following_rate_id = uuid4()
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,occurred_at,actor_id) VALUES (%s,%s,12000,'2027-02-01',now(),%s)",
        (following_rate_id, service_id, actor_id),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET service_rate_id=%s,"
        "service_monthly_rate_usd_cents=12000,amount_usd_cents=12000 WHERE id=%s",
        (following_rate_id, service_second_component_id),
    )
    connection.execute(
        "UPDATE app.invoice_lines SET amount_usd_cents=%s WHERE id=%s",
        (prorated_service_amount + 12000, service_line_id),
    )
    connection.execute(
        "UPDATE app.invoices SET original_total_usd_cents=%s,version=3,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (total_amount + prorated_service_amount + 12000, actor_id, invoice_id),
    )
    with pytest.raises(Error) as different_component_rates_require_null_line_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=4,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert different_component_rates_require_null_line_snapshot.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_lines SET service_rate_id=NULL,contractual_monthly_usd_cents=NULL "
        "WHERE id=%s",
        (service_line_id,),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),issued_by=%s,"
        "version=4,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, actor_id, invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    first_day_actor, _, first_day_tenant, first_day_lease = setup_signed_lease(
        connection, with_occupancy=False
    )
    first_day = date(2027, 3, 1)
    first_day_occupancy = uuid4()
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (
            first_day_occupancy,
            first_day_lease,
            first_day_tenant,
            first_day,
            first_day_actor,
            first_day_actor,
        ),
    )
    first_day_invoice = uuid4()
    first_day_line = uuid4()
    first_day_component = uuid4()
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,due_date,billing_period_start,billing_period_end,rent_billing_kind,"
        "source_occupancy_id,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by) VALUES "
        "(%s,%s,%s,%s,'RENT','DRAFT',%s,%s,%s,'2027-03-31','INITIAL',%s,80000,"
        "'INITIAL_RENT_SEVEN_DAYS','BR-RENT-017',%s,%s)",
        (
            first_day_invoice,
            f"INV-{first_day_invoice.hex}",
            first_day_tenant,
            first_day_lease,
            first_day,
            first_day + timedelta(days=7),
            first_day,
            first_day_occupancy,
            first_day_actor,
            first_day_actor,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,period_start,period_end,source_lease_id,"
        "contractual_monthly_usd_cents,calculation_trace,created_by) VALUES "
        "(%s,%s,1,'RENT','Initial full month',80000,%s,'2027-03-31',%s,80000,%s,%s)",
        (
            first_day_line,
            first_day_invoice,
            first_day,
            first_day_lease,
            Jsonb({"formula": "initial_full_month"}),
            first_day_actor,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,"
        "contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_FOLLOWING_MONTH',%s,"
        "'2027-03-31',80000,31,31,80000,%s,%s)",
        (
            first_day_component,
            first_day_line,
            first_day,
            Jsonb({"formula": "initial_full_month"}),
            first_day_actor,
        ),
    )
    with pytest.raises(Error) as mislabeled_first_day:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (first_day_actor, first_day_actor, first_day_invoice),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mislabeled_first_day.value.sqlstate == "23514"
    set_draft_correction_context(
        connection, actor_id=first_day_actor, reason="Correct first-day Initial Rent evidence"
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components "
        "SET component_kind='PRORATED_MOVE_IN_MONTH' WHERE id=%s",
        (first_day_component,),
    )
    connection.execute(
        "UPDATE app.invoice_lines SET billable_days=1,calendar_days=31 WHERE id=%s",
        (first_day_line,),
    )
    with pytest.raises(Error) as contradictory_single_component_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (first_day_actor, first_day_actor, first_day_invoice),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert contradictory_single_component_snapshot.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoice_lines SET billable_days=31,calendar_days=31 WHERE id=%s",
        (first_day_line,),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),issued_by=%s,"
        "version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (first_day_actor, first_day_actor, first_day_invoice),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_invoice_ownership_sources_issuance_and_permanent_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, tenant_id, lease_id = setup_signed_lease(connection)
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct reviewed Invoice DRAFT detail"
    )
    invoice_id, line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
    )
    assert connection.execute(
        "SELECT status,original_total_usd_cents FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone() == ("UNPAID", 80000)
    assert connection.execute(
        "SELECT app.invoice_adjusted_line_obligation(%s)", (line_id,)
    ).fetchone() == (80000,)
    future_line_invoice_id, future_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 10, 1),
        issue=False,
        line_created_at=datetime(2100, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(Error) as issue_before_line_evidence:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, future_line_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert issue_before_line_evidence.value.sqlstate == "23514"
    connection.execute(
        "DELETE FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
        (future_line_id,),
    )
    connection.execute("DELETE FROM app.invoice_lines WHERE id=%s", (future_line_id,))
    with pytest.raises(Error) as payment_dependent_status:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='PARTIALLY_PAID',version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
    assert payment_dependent_status.value.sqlstate == "55000"
    with pytest.raises(Error) as void_without_event:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_without_event.value.sqlstate == "23514"
    with pytest.raises(Error) as issued_rewrite:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET due_date=due_date+1,version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
    assert issued_rewrite.value.sqlstate == "55000"
    with pytest.raises(Error) as line_delete:
        with connection.transaction():
            connection.execute("DELETE FROM app.invoice_lines WHERE id=%s", (line_id,))
    assert line_delete.value.sqlstate == "55000"

    draft_invoice_id, draft_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 3, 1),
        issue=False,
    )
    component_row = connection.execute(
        "SELECT id FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
        (draft_line_id,),
    ).fetchone()
    assert component_row is not None
    component_id = component_row[0]
    with pytest.raises(Error) as draft_change_without_attribution:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('app.draft_correction_actor_id','',true),"
                "set_config('app.draft_correction_reason','',true)"
            )
            connection.execute(
                "UPDATE app.invoice_lines SET description='Unattributed DRAFT edit',"
                "last_changed_by=%s WHERE id=%s",
                (actor_id, draft_line_id),
            )
    assert draft_change_without_attribution.value.sqlstate == "55000"
    with pytest.raises(Error) as mismatched_rent_arithmetic:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_line_calculation_components SET amount_usd_cents=1 WHERE id=%s",
                (component_id,),
            )
            connection.execute(
                "UPDATE app.invoice_lines SET amount_usd_cents=1 WHERE id=%s",
                (draft_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET original_total_usd_cents=1,status='UNPAID',"
                "issued_at=statement_timestamp(),issued_by=%s,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, actor_id, draft_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mismatched_rent_arithmetic.value.sqlstate == "23514"
    detail_editor_id = uuid4()
    connection.execute(
        "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
        "lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,'Detail Editor',"
        "'Detail Editor','active','optional','test')",
        (detail_editor_id, f"detail-editor-{detail_editor_id}"),
    )
    with pytest.raises(Error) as detail_editor_without_matching_invoice_update:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET description='Unauthorized attribution',"
                "last_changed_by=%s WHERE id=%s",
                (detail_editor_id, draft_line_id),
            )
    assert detail_editor_without_matching_invoice_update.value.sqlstate == "55000"
    set_draft_correction_context(
        connection, actor_id=detail_editor_id, reason="Review Invoice DRAFT detail"
    )
    connection.execute(
        "UPDATE app.invoices SET version=2,updated_at=statement_timestamp(),updated_by=%s "
        "WHERE id=%s",
        (detail_editor_id, draft_invoice_id),
    )
    connection.execute(
        "UPDATE app.invoice_lines SET description='Reviewed Rent detail',last_changed_by=%s "
        "WHERE id=%s",
        (detail_editor_id, draft_line_id),
    )
    connection.execute(
        "UPDATE app.invoice_line_calculation_components SET calculation_trace=%s,"
        "last_changed_by=%s WHERE id=%s",
        (Jsonb({"formula": "reviewed_monthly_rent"}), detail_editor_id, component_id),
    )
    assert connection.execute(
        "SELECT line.last_changed_by,component.last_changed_by "
        "FROM app.invoice_lines AS line "
        "JOIN app.invoice_line_calculation_components AS component "
        "ON component.invoice_line_id=line.id WHERE line.id=%s",
        (draft_line_id,),
    ).fetchone() == (detail_editor_id, detail_editor_id)
    revision_rows = connection.execute(
        "SELECT entity_kind,entity_id,operation,reason,changed_by,"
        "before_state IS NOT NULL,after_state IS NOT NULL "
        "FROM app.invoice_draft_revision_events WHERE invoice_id=%s ORDER BY id",
        (draft_invoice_id,),
    ).fetchall()
    assert revision_rows == [
        (
            "INVOICE",
            draft_invoice_id,
            "UPDATE",
            "Review Invoice DRAFT detail",
            detail_editor_id,
            True,
            True,
        ),
        (
            "LINE",
            draft_line_id,
            "UPDATE",
            "Review Invoice DRAFT detail",
            detail_editor_id,
            True,
            True,
        ),
        (
            "COMPONENT",
            component_id,
            "UPDATE",
            "Review Invoice DRAFT detail",
            detail_editor_id,
            True,
            True,
        ),
    ]
    assert connection.execute(
        "SELECT before_state->>'description',after_state->>'description' "
        "FROM app.invoice_draft_revision_events WHERE invoice_id=%s "
        "AND entity_kind='LINE' AND operation='UPDATE'",
        (draft_invoice_id,),
    ).fetchone() == ("Monthly Rent", "Reviewed Rent detail")
    with pytest.raises(Error) as direct_draft_revision_insert:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_draft_revision_events(invoice_id,entity_kind,"
                "entity_id,operation,before_state,after_state,reason,changed_by,transaction_id) "
                "VALUES (%s,'LINE',%s,'UPDATE','{}'::jsonb,'{}'::jsonb,'Forged event',%s,1)",
                (draft_invoice_id, draft_line_id, detail_editor_id),
            )
    assert direct_draft_revision_insert.value.sqlstate == "55000"
    with pytest.raises(Error) as move_line_parent:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET invoice_id=%s WHERE id=%s",
                (invoice_id, draft_line_id),
            )
    assert move_line_parent.value.sqlstate == "55000"
    with pytest.raises(Error) as move_component_parent:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_line_calculation_components SET invoice_line_id=%s WHERE id=%s",
                (line_id, component_id),
            )
    assert move_component_parent.value.sqlstate == "55000"
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Attempt mismatched DRAFT detail deletion"
    )
    with pytest.raises(Error) as delete_component_with_mismatched_actor:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.invoice_line_calculation_components WHERE id=%s",
                (component_id,),
            )
    assert delete_component_with_mismatched_actor.value.sqlstate == "55000"
    set_draft_correction_context(
        connection, actor_id=detail_editor_id, reason="Review Invoice DRAFT detail"
    )
    connection.execute(
        "DELETE FROM app.invoice_line_calculation_components WHERE id=%s", (component_id,)
    )
    connection.execute("DELETE FROM app.invoice_lines WHERE id=%s", (draft_line_id,))
    assert connection.execute(
        "SELECT count(*) FROM app.invoice_lines WHERE invoice_id=%s", (draft_invoice_id,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT entity_kind,operation,after_state IS NULL,reason,changed_by "
        "FROM app.invoice_draft_revision_events WHERE invoice_id=%s ORDER BY id DESC LIMIT 2",
        (draft_invoice_id,),
    ).fetchall() == [
        ("LINE", "DELETE", True, "Review Invoice DRAFT detail", detail_editor_id),
        ("COMPONENT", "DELETE", True, "Review Invoice DRAFT detail", detail_editor_id),
    ]
    inactive_delete_actor_id = uuid4()
    connection.execute(
        "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
        "lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,'Inactive Delete Actor',"
        "'Inactive Delete Actor','active','optional','test')",
        (inactive_delete_actor_id, f"inactive-delete-{inactive_delete_actor_id}"),
    )
    inactive_draft_invoice_id, inactive_draft_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=inactive_delete_actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 11, 1),
        issue=False,
    )
    set_draft_correction_context(
        connection,
        actor_id=inactive_delete_actor_id,
        reason="Attempt inactive DRAFT detail deletion",
    )
    connection.execute(
        "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
        (inactive_delete_actor_id,),
    )
    with pytest.raises(Error) as delete_line_with_inactive_actor:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.invoice_lines WHERE id=%s", (inactive_draft_line_id,)
            )
    assert delete_line_with_inactive_actor.value.sqlstate == "55000"
    assert connection.execute(
        "SELECT status FROM app.invoices WHERE id=%s", (inactive_draft_invoice_id,)
    ).fetchone() == ("DRAFT",)
    revision_id_row = connection.execute(
        "SELECT id FROM app.invoice_draft_revision_events WHERE invoice_id=%s ORDER BY id LIMIT 1",
        (draft_invoice_id,),
    ).fetchone()
    assert revision_id_row is not None
    with pytest.raises(Error) as rewrite_draft_revision:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_draft_revision_events SET reason='Rewritten' WHERE id=%s",
                (revision_id_row[0],),
            )
    assert rewrite_draft_revision.value.sqlstate == "55000"
    with pytest.raises(Error) as erase_draft_revision:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.invoice_draft_revision_events WHERE id=%s",
                (revision_id_row[0],),
            )
    assert erase_draft_revision.value.sqlstate == "55000"


def test_lease_customer_and_authorized_nonrecurring_source_are_enforced(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, tenant_id, other_customer = setup_sources(connection)
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct authorized obligation DRAFT source"
    )
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
        signed=False,
    )
    connection.execute(
        "SELECT set_config('app.lease_signer_actor_id',%s,true)",
        (str(actor_id),),
    )
    connection.execute(
        "UPDATE app.lease_signers SET signed_at=statement_timestamp()+interval '1 day' "
        "WHERE lease_id=%s AND customer_id=%s",
        (lease_id, tenant_id),
    )
    sign_lease(connection, lease_id, actor_id)
    with pytest.raises(Error) as issued_before_signer:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_id,
                lease_id=lease_id,
            )
    assert issued_before_signer.value.sqlstate == "23514"
    with pytest.raises(Error) as wrong_owner:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO app.invoices(
                    id,invoice_number,customer_id,lease_id,primary_category,status,
                    invoice_date,due_date,billing_period_start,billing_period_end,
                    rent_billing_kind,original_total_usd_cents,due_date_rule,due_date_source,
                    created_by,updated_by
                ) VALUES (%s,%s,%s,%s,'RENT','DRAFT','2027-02-01','2027-02-05',
                    '2027-02-01','2027-02-28','RECURRING',80000,
                    'RECURRING_RENT_FIFTH','BR-RENT-018',%s,%s)
                """,
                (uuid4(), f"INV-{uuid4().hex}", other_customer, lease_id, actor_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert wrong_owner.value.sqlstate == "23514"

    with pytest.raises(Error) as unbound_damage_source:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
                "inspection_damage_finding_id,description,authorized_amount_usd_cents,"
                "governing_due_date,due_date_source,source_reference,authorized_at,"
                "authorized_by,authorization_reference) VALUES "
                "(%s,%s,'DAMAGE_CHARGES',%s,'Unbound damage',2500,current_date+7,"
                "'unbound-inspection','unbound-inspection',"
                "statement_timestamp(),%s,'invoice.nonrecurring.authorize')",
                (uuid4(), other_customer, uuid4(), actor_id),
            )
    assert unbound_damage_source.value.sqlstate == "23514"

    with pytest.raises(Error) as issued_before_obligation_authorization:
        with connection.transaction():
            future_obligation_id = uuid4()
            future_invoice_id = uuid4()
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
                "description,authorized_amount_usd_cents,governing_due_date,due_date_source,"
                "source_reference,authorized_at,"
                "authorized_by,authorization_reference) VALUES (%s,%s,'MISCELLANEOUS_CHARGES',"
                "'Future authorization',2500,current_date+7,'future-authorization',"
                "'future-authorization',"
                "statement_timestamp()+interval '1 day',%s,'invoice.nonrecurring.authorize')",
                (future_obligation_id, other_customer, actor_id),
            )
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "current_date,current_date+7,2500,'GOVERNING_SOURCE','future-authorization',%s,%s)",
                (
                    future_invoice_id,
                    f"INV-{future_invoice_id.hex}",
                    other_customer,
                    actor_id,
                    actor_id,
                ),
            )
            connection.execute(
                "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,authorized_obligation_id,calculation_trace,created_by) VALUES "
                "(%s,%s,1,'MISCELLANEOUS_CHARGES','Future authorization',2500,%s,%s,%s)",
                (
                    uuid4(),
                    future_invoice_id,
                    future_obligation_id,
                    Jsonb({"source": "future-authorization"}),
                    actor_id,
                ),
            )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, future_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert issued_before_obligation_authorization.value.sqlstate == "23514"

    obligation_id = uuid4()
    invoice_id = uuid4()
    line_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.authorized_nonrecurring_obligations(
            id,customer_id,category,description,authorized_amount_usd_cents,
            governing_due_date,due_date_source,source_reference,authorized_at,
            authorized_by,authorization_reference
        ) VALUES (%s,%s,'MISCELLANEOUS_CHARGES','Approved key replacement',2500,
            current_date+7,'signed-administration-record','signed-administration-record',
            statement_timestamp(),%s,'invoice.nonrecurring.authorize')
        """,
        (obligation_id, other_customer, actor_id),
    )
    with pytest.raises(Error) as replayed_nonrecurring_authorization:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
                "description,authorized_amount_usd_cents,governing_due_date,due_date_source,"
                "source_reference,authorized_at,"
                "authorized_by,authorization_reference) VALUES (%s,%s,"
                "'MISCELLANEOUS_CHARGES','Replayed key replacement',2500,"
                "current_date+7,'signed-administration-record','signed-administration-record',"
                "statement_timestamp(),%s,"
                "'invoice.nonrecurring.authorize')",
                (uuid4(), other_customer, actor_id),
            )
    assert replayed_nonrecurring_authorization.value.sqlstate == "23505"
    connection.execute(
        """
        INSERT INTO app.invoices(
            id,invoice_number,customer_id,primary_category,status,invoice_date,due_date,
            original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by
        ) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',current_date,current_date+7,
            2500,'GOVERNING_SOURCE','signed-administration-record',%s,%s)
        """,
        (invoice_id, f"INV-{invoice_id.hex}", other_customer, actor_id, actor_id),
    )
    connection.execute(
        """
        INSERT INTO app.invoice_lines(
            id,invoice_id,line_sequence,category,description,amount_usd_cents,
            authorized_obligation_id,calculation_trace,created_by
        ) VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES','Approved key replacement',2500,%s,%s,%s)
        """,
        (
            line_id,
            invoice_id,
            obligation_id,
            Jsonb({"source": "authorized_obligation"}),
            actor_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as retroactive_due_date:
        with connection.transaction():
            retroactive_invoice_id = uuid4()
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "current_date,current_date-1,2500,'GOVERNING_SOURCE',"
                "'signed-administration-record',%s,%s)",
                (
                    retroactive_invoice_id,
                    f"INV-{retroactive_invoice_id.hex}",
                    other_customer,
                    actor_id,
                    actor_id,
                ),
            )
    assert retroactive_due_date.value.sqlstate == "23514"
    with pytest.raises(Error) as backdated_governing_source:
        with connection.transaction():
            backdated_obligation_id = uuid4()
            backdated_invoice_id = uuid4()
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
                "description,authorized_amount_usd_cents,governing_due_date,due_date_source,"
                "source_reference,authorized_at,authorized_by,authorization_reference) VALUES "
                "(%s,%s,'MISCELLANEOUS_CHARGES','Backdated source',2500,current_date-1,"
                "'backdated-source','backdated-source',statement_timestamp(),%s,"
                "'invoice.nonrecurring.authorize')",
                (backdated_obligation_id, other_customer, actor_id),
            )
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "current_date-1,current_date-1,2500,'GOVERNING_SOURCE','backdated-source',%s,%s)",
                (
                    backdated_invoice_id,
                    f"INV-{backdated_invoice_id.hex}",
                    other_customer,
                    actor_id,
                    actor_id,
                ),
            )
    assert backdated_governing_source.value.sqlstate == "23514"
    for column, value in (
        ("due_date", "current_date+8"),
        ("due_date_source", "'unrelated-governing-source'"),
    ):
        with pytest.raises(Error) as forged_obligation_header:
            with connection.transaction():
                connection.execute(
                    f"UPDATE app.invoices SET {column}={value},status='UNPAID',"
                    "issued_at=statement_timestamp(),issued_by=%s,version=2,"
                    "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                    (actor_id, actor_id, invoice_id),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert forged_obligation_header.value.sqlstate == "23514"
    with pytest.raises(Error) as forged_obligation_description:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET description='Unrelated charge' WHERE id=%s",
                (line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert forged_obligation_description.value.sqlstate == "23514"
    with pytest.raises(Error) as final_header_customer_drift:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET customer_id=%s,status='UNPAID',"
                "issued_at=statement_timestamp(),issued_by=%s,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (tenant_id, actor_id, actor_id, invoice_id),
            )
    assert final_header_customer_drift.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),issued_by=%s,"
        "version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, actor_id, invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT lease_id,status FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone() == (None, "UNPAID")
    void_at = datetime.now(UTC) + timedelta(seconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (void_at, actor_id, invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Invalid source Invoice',%s,%s,"
        "'invoice.void')",
        (uuid4(), invoice_id, void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    replacement_invoice_id = uuid4()
    replacement_line_id = uuid4()
    replacement_issue_at = void_at + timedelta(microseconds=1)
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
        "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
        "current_date,current_date+7,2500,'GOVERNING_SOURCE',"
        "'signed-administration-record',%s,%s)",
        (
            replacement_invoice_id,
            f"INV-{replacement_invoice_id.hex}",
            other_customer,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,authorized_obligation_id,calculation_trace,created_by) VALUES "
        "(%s,%s,1,'MISCELLANEOUS_CHARGES','Approved key replacement',2500,%s,%s,%s)",
        (
            replacement_line_id,
            replacement_invoice_id,
            obligation_id,
            Jsonb({"source": "authorized_obligation_replacement"}),
            actor_id,
        ),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,version=2,"
        "updated_at=%s,updated_by=%s WHERE id=%s",
        (
            replacement_issue_at,
            actor_id,
            replacement_issue_at,
            actor_id,
            replacement_invoice_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as duplicate_active_obligation:
        with connection.transaction():
            duplicate_invoice_id = uuid4()
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "current_date,current_date+7,2500,'GOVERNING_SOURCE',"
                "'signed-administration-record',%s,%s)",
                (
                    duplicate_invoice_id,
                    f"INV-{duplicate_invoice_id.hex}",
                    other_customer,
                    actor_id,
                    actor_id,
                ),
            )
            connection.execute(
                "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,authorized_obligation_id,calculation_trace,created_by) VALUES "
                "(%s,%s,1,'MISCELLANEOUS_CHARGES','Approved key replacement',2500,%s,%s,%s)",
                (
                    uuid4(),
                    duplicate_invoice_id,
                    obligation_id,
                    Jsonb({"source": "duplicate_active_obligation"}),
                    actor_id,
                ),
            )
    assert duplicate_active_obligation.value.sqlstate == "23P01"


def test_rent_service_sources_preserve_evidence_and_utility_defers_without_source_fk(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct Rent and Service DRAFT evidence"
    )
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    sign_lease(connection, lease_id, actor_id)
    service_id = uuid4()
    rate_id = uuid4()
    approval_id = uuid4()
    term_id = uuid4()
    connection.execute(
        "INSERT INTO app.property_services(id,property_id,service_code,display_name,configured_by,"
        "created_by,updated_by) VALUES (%s,%s,'TRASH','Trash Collection',%s,%s,%s)",
        (service_id, property_id, actor_id, actor_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,occurred_at,actor_id) VALUES (%s,%s,10000,'2027-01-01',now(),%s)",
        (rate_id, service_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.property_service_approval_periods(id,property_service_id,effective_from,"
        "effective_through,approval_reference,approved_at,approved_by,reason) "
        "VALUES (%s,%s,'2027-01-01','2027-12-31','owner-service-approval',now(),%s,"
        "'Approved recurring Service')",
        (approval_id, service_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,applicable_from,"
        "applicable_through,service_approval_period_id,terms_reference,recorded_at,recorded_by) "
        "VALUES (%s,%s,%s,'2027-01-01','2027-12-31',%s,'signed-lease-service',now(),%s)",
        (term_id, lease_id, service_id, approval_id, actor_id),
    )
    invoice_id, rent_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        issue=False,
    )
    with pytest.raises(Error) as contradictory_recurring_rent_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET billable_days=1 WHERE id=%s", (rent_line_id,)
            )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert contradictory_recurring_rent_snapshot.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoices SET original_total_usd_cents=90000,version=2,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, invoice_id),
    )
    service_line_id = uuid4()
    with pytest.raises(Error) as contradictory_service_source:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO app.invoice_lines(
                    id,invoice_id,line_sequence,category,description,amount_usd_cents,
                    period_start,period_end,source_lease_id,utility_consumption_period_id,
                    property_service_id,service_rate_id,lease_service_term_id,
                    service_approval_period_id,contractual_monthly_usd_cents,billable_days,
                    calendar_days,calculation_trace,created_by
                ) VALUES (%s,%s,2,'SERVICE_CHARGES','Contradictory Service',10000,
                    '2027-02-01','2027-02-28',%s,%s,%s,%s,%s,%s,10000,28,28,%s,%s)
                """,
                (
                    uuid4(),
                    invoice_id,
                    lease_id,
                    uuid4(),
                    service_id,
                    rate_id,
                    term_id,
                    approval_id,
                    Jsonb({"formula": "invalid_mixed_source"}),
                    actor_id,
                ),
            )
    assert contradictory_service_source.value.sqlstate == "23514"
    connection.execute(
        """
        INSERT INTO app.invoice_lines(
            id,invoice_id,line_sequence,category,description,amount_usd_cents,
            period_start,period_end,source_lease_id,property_service_id,service_rate_id,
            lease_service_term_id,service_approval_period_id,contractual_monthly_usd_cents,
            billable_days,calendar_days,calculation_trace,created_by
        ) VALUES (%s,%s,2,'SERVICE_CHARGES','Trash Collection',10000,
            '2027-02-01','2027-02-28',%s,%s,%s,%s,%s,10000,28,28,%s,%s)
        """,
        (
            service_line_id,
            invoice_id,
            lease_id,
            service_id,
            rate_id,
            term_id,
            approval_id,
            Jsonb({"formula": "monthly_service", "amount_usd_cents": 10000}),
            actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.invoice_line_calculation_components(
            id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
            service_rate_id,service_monthly_rate_usd_cents,billable_days,calendar_days,
            amount_usd_cents,calculation_trace,created_by
        ) VALUES (%s,%s,1,'FULL_RECURRING_MONTH','2027-02-01','2027-02-28',
            %s,10000,28,28,10000,%s,%s)
        """,
        (
            uuid4(),
            service_line_id,
            rate_id,
            Jsonb({"formula": "monthly_service", "amount_usd_cents": 10000}),
            actor_id,
        ),
    )
    with pytest.raises(Error) as service_component_with_rent_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_line_calculation_components "
                "SET contractual_monthly_usd_cents=10000 WHERE invoice_line_id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert service_component_with_rent_snapshot.value.sqlstate == "23514"
    with pytest.raises(Error) as missing_single_component_snapshot:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET service_rate_id=NULL WHERE id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert missing_single_component_snapshot.value.sqlstate == "23514"
    with pytest.raises(Error) as mismatched_service_arithmetic:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_line_calculation_components SET amount_usd_cents=9999 "
                "WHERE invoice_line_id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoice_lines SET amount_usd_cents=9999 WHERE id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET original_total_usd_cents=89999,status='UNPAID',"
                "issued_at=statement_timestamp(),issued_by=%s,version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert mismatched_service_arithmetic.value.sqlstate == "23514"
    with pytest.raises(Error) as fragmented_service_rounding:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoice_lines SET amount_usd_cents=9996 WHERE id=%s",
                (service_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET original_total_usd_cents=89996,version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
            for day in range(1, 29):
                component_date = date(2027, 2, day)
                connection.execute(
                    "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
                    "component_sequence,component_kind,period_start,period_end,service_rate_id,"
                    "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
                    "calculation_trace,created_by) VALUES (%s,%s,%s,"
                    "'OTHER_APPROVED_COMPONENT',%s,%s,%s,10000,1,28,357,%s,%s)",
                    (
                        uuid4(),
                        service_line_id,
                        day,
                        component_date,
                        component_date,
                        rate_id,
                        Jsonb({"formula": "fragmented_service"}),
                        actor_id,
                    ),
                )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=4,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert fragmented_service_rounding.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),issued_by=%s,"
        "version=3,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, actor_id, invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT category,property_service_id,service_rate_id FROM app.invoice_lines WHERE id=%s",
        (service_line_id,),
    ).fetchone() == ("SERVICE_CHARGES", service_id, rate_id)

    service_only_invoice_id, removed_rent_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 3, 1),
        issue=False,
    )
    connection.execute(
        "DELETE FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
        (removed_rent_line_id,),
    )
    connection.execute("DELETE FROM app.invoice_lines WHERE id=%s", (removed_rent_line_id,))
    service_only_line_id = uuid4()
    connection.execute(
        "UPDATE app.invoices SET original_total_usd_cents=10000,version=2,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, service_only_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,period_start,period_end,source_lease_id,property_service_id,"
        "service_rate_id,lease_service_term_id,service_approval_period_id,"
        "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,created_by) "
        "VALUES (%s,%s,1,'SERVICE_CHARGES','Trash Collection',10000,'2027-03-01',"
        "'2027-03-31',%s,%s,%s,%s,%s,10000,31,31,%s,%s)",
        (
            service_only_line_id,
            service_only_invoice_id,
            lease_id,
            service_id,
            rate_id,
            term_id,
            approval_id,
            Jsonb({"formula": "monthly_service", "amount_usd_cents": 10000}),
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,service_rate_id,"
        "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',"
        "'2027-03-01','2027-03-31',%s,10000,31,31,10000,%s,%s)",
        (
            uuid4(),
            service_only_line_id,
            rate_id,
            Jsonb({"formula": "monthly_service", "amount_usd_cents": 10000}),
            actor_id,
        ),
    )
    with pytest.raises(Error) as rent_invoice_without_rent_line:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, service_only_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert rent_invoice_without_rent_line.value.sqlstate == "23514"

    with pytest.raises(Error) as split_recurring_rounding:
        with connection.transaction():
            split_invoice_id, split_line_id = create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_id,
                lease_id=lease_id,
                period_start=date(2027, 4, 1),
                issue=False,
            )
            connection.execute(
                "DELETE FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
                (split_line_id,),
            )
            connection.execute(
                "UPDATE app.invoice_lines SET amount_usd_cents=80010 WHERE id=%s",
                (split_line_id,),
            )
            connection.execute(
                "UPDATE app.invoices SET original_total_usd_cents=80010,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, split_invoice_id),
            )
            for day in range(1, 31):
                component_date = date(2027, 4, day)
                connection.execute(
                    "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
                    "component_sequence,component_kind,period_start,period_end,"
                    "contractual_monthly_usd_cents,billable_days,calendar_days,"
                    "amount_usd_cents,calculation_trace,created_by) VALUES (%s,%s,%s,"
                    "'OTHER_APPROVED_COMPONENT',%s,%s,80000,1,30,2667,%s,%s)",
                    (
                        uuid4(),
                        split_line_id,
                        day,
                        component_date,
                        component_date,
                        Jsonb({"formula": "invalid_repeated_rounding"}),
                        actor_id,
                    ),
                )
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, split_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert split_recurring_rounding.value.sqlstate == "23514"

    invoice_issue_time = datetime(2027, 4, 30, 12, 0, tzinfo=UTC)
    prior_source_time = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
    future_source_time = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    for future_source in ("rate", "approval", "term"):
        with pytest.raises(Error) as future_service_source:
            with connection.transaction():
                future_service_id = uuid4()
                future_rate_id = uuid4()
                future_approval_id = uuid4()
                future_term_id = uuid4()
                future_invoice_id = uuid4()
                future_line_id = uuid4()
                connection.execute(
                    "INSERT INTO app.property_services(id,property_id,service_code,display_name,"
                    "configured_by,created_by,updated_by) VALUES (%s,%s,%s,"
                    "'Chronology Service',%s,%s,%s)",
                    (
                        future_service_id,
                        property_id,
                        f"CHRONOLOGY_{future_source.upper()}",
                        actor_id,
                        actor_id,
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.service_rates(id,property_service_id,"
                    "monthly_rate_usd_cents,effective_date,occurred_at,actor_id) VALUES "
                    "(%s,%s,10000,'2027-04-01',%s,%s)",
                    (
                        future_rate_id,
                        future_service_id,
                        future_source_time if future_source == "rate" else prior_source_time,
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.property_service_approval_periods(id,property_service_id,"
                    "effective_from,effective_through,approval_reference,approved_at,approved_by,"
                    "reason) VALUES (%s,%s,'2027-01-01','2027-12-31',%s,%s,%s,"
                    "'Chronology evidence')",
                    (
                        future_approval_id,
                        future_service_id,
                        f"chronology-{future_source}",
                        future_source_time if future_source == "approval" else prior_source_time,
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,"
                    "applicable_from,applicable_through,service_approval_period_id,terms_reference,"
                    "recorded_at,recorded_by) VALUES (%s,%s,%s,'2027-01-01','2027-12-31',%s,"
                    "%s,%s,%s)",
                    (
                        future_term_id,
                        lease_id,
                        future_service_id,
                        future_approval_id,
                        f"chronology-{future_source}",
                        future_source_time if future_source == "term" else prior_source_time,
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                    "primary_category,status,invoice_date,due_date,billing_period_start,"
                    "billing_period_end,original_total_usd_cents,due_date_rule,due_date_source,"
                    "created_by,updated_by) VALUES (%s,%s,%s,%s,'SERVICE_CHARGES','DRAFT',"
                    "'2027-04-30','2027-05-07','2027-04-01','2027-04-30',10000,"
                    "'GOVERNING_SOURCE','approved-service',%s,%s)",
                    (
                        future_invoice_id,
                        f"INV-{future_invoice_id.hex}",
                        tenant_id,
                        lease_id,
                        actor_id,
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,"
                    "description,amount_usd_cents,period_start,period_end,source_lease_id,"
                    "property_service_id,service_rate_id,lease_service_term_id,"
                    "service_approval_period_id,contractual_monthly_usd_cents,billable_days,"
                    "calendar_days,calculation_trace,created_by) VALUES (%s,%s,1,"
                    "'SERVICE_CHARGES','Chronology Service',10000,'2027-04-01','2027-04-30',"
                    "%s,%s,%s,%s,%s,10000,30,30,%s,%s)",
                    (
                        future_line_id,
                        future_invoice_id,
                        lease_id,
                        future_service_id,
                        future_rate_id,
                        future_term_id,
                        future_approval_id,
                        Jsonb({"formula": "monthly_service"}),
                        actor_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
                    "component_sequence,component_kind,period_start,period_end,service_rate_id,"
                    "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
                    "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',"
                    "'2027-04-01','2027-04-30',%s,10000,30,30,10000,%s,%s)",
                    (
                        uuid4(),
                        future_line_id,
                        future_rate_id,
                        Jsonb({"formula": "monthly_service"}),
                        actor_id,
                    ),
                )
                connection.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
                    "version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                    (invoice_issue_time, actor_id, actor_id, future_invoice_id),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert future_service_source.value.sqlstate == "23514"

    utility_rate_id = uuid4()
    utility_period_id = uuid4()
    utility_invoice_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
        "rate_usd_per_unit,effective_date,notice_at,notice_evidence,occurred_at,actor_id) "
        "VALUES (%s,%s,'ELECTRICITY','KWH',0.25,'2027-01-01','2026-12-01',"
        "'customer-notice',now(),%s)",
        (utility_rate_id, property_id, actor_id),
    )
    current_utility_rate_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
        "rate_usd_per_unit,effective_date,notice_at,notice_evidence,occurred_at,actor_id) "
        "VALUES (%s,%s,'ELECTRICITY','KWH',0.25,'2027-02-01','2027-01-01',"
        "'updated-customer-notice',now(),%s)",
        (current_utility_rate_id, property_id, actor_id),
    )
    with pytest.raises(Error) as half_open_utility_invoice:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                "primary_category,status,invoice_date,due_date,billing_period_start,"
                "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by) "
                "VALUES (%s,%s,%s,%s,'UTILITIES','DRAFT','2027-02-28','2027-03-07',"
                "'2027-02-01',2500,'GOVERNING_SOURCE','half-open-period',%s,%s)",
                (
                    uuid4(),
                    f"INV-{uuid4().hex}",
                    tenant_id,
                    lease_id,
                    actor_id,
                    actor_id,
                ),
            )
    assert half_open_utility_invoice.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,due_date,billing_period_start,billing_period_end,original_total_usd_cents,"
        "due_date_rule,due_date_source,created_by,updated_by) VALUES (%s,%s,%s,%s,'UTILITIES',"
        "'DRAFT','2027-02-28','2027-03-07','2027-02-01','2027-02-28',2500,"
        "'GOVERNING_SOURCE','validated-consumption-period',%s,%s)",
        (
            utility_invoice_id,
            f"INV-{utility_invoice_id.hex}",
            tenant_id,
            lease_id,
            actor_id,
            actor_id,
        ),
    )
    with pytest.raises(Error) as half_open_utility_line:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,period_start,source_lease_id,utility_consumption_period_id,"
                "utility_rate_id,quantity,unit_rate_usd,calculation_trace,created_by) VALUES "
                "(%s,%s,1,'UTILITIES','Electricity',2500,'2027-02-01',%s,%s,%s,100,0.25,"
                "%s,%s)",
                (
                    uuid4(),
                    utility_invoice_id,
                    lease_id,
                    utility_period_id,
                    current_utility_rate_id,
                    Jsonb({"quantity": "100", "unit_rate_usd": "0.25"}),
                    actor_id,
                ),
            )
    assert half_open_utility_line.value.sqlstate == "23514"
    with pytest.raises(Error) as superseded_utility_rate:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,period_start,period_end,source_lease_id,"
                "utility_consumption_period_id,utility_rate_id,quantity,unit_rate_usd,"
                "calculation_trace,created_by) VALUES (%s,%s,1,'UTILITIES','Electricity',2500,"
                "'2027-02-01','2027-02-28',%s,%s,%s,100,0.25,%s,%s)",
                (
                    uuid4(),
                    utility_invoice_id,
                    lease_id,
                    utility_period_id,
                    utility_rate_id,
                    Jsonb({"quantity": "100", "unit_rate_usd": "0.25"}),
                    actor_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert superseded_utility_rate.value.sqlstate == "23514"
    with pytest.raises(Error) as unbound_utility_source:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,period_start,period_end,source_lease_id,"
                "utility_consumption_period_id,utility_rate_id,quantity,unit_rate_usd,"
                "calculation_trace,created_by) VALUES (%s,%s,1,'UTILITIES','Electricity',2500,"
                "'2027-02-01','2027-02-28',%s,%s,%s,100,0.25,%s,%s)",
                (
                    uuid4(),
                    utility_invoice_id,
                    lease_id,
                    utility_period_id,
                    current_utility_rate_id,
                    Jsonb({"quantity": "100", "unit_rate_usd": "0.25"}),
                    actor_id,
                ),
            )
    assert unbound_utility_source.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.invoice_lines WHERE utility_consumption_period_id=%s",
        (utility_period_id,),
    ).fetchone() == (0,)


def test_service_invoice_ignores_rate_recorded_after_issuance_snapshot(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=tenant_id,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    sign_lease(connection, lease_id, actor_id)
    issue_at = datetime.now(UTC) + timedelta(seconds=1)
    service_id = uuid4()
    current_rate_id = uuid4()
    approval_id = uuid4()
    term_id = uuid4()
    invoice_id = uuid4()
    line_id = uuid4()
    connection.execute(
        "INSERT INTO app.property_services(id,property_id,service_code,display_name,configured_by,"
        "created_by,updated_by) VALUES (%s,%s,'SNAPSHOT','Snapshot Service',%s,%s,%s)",
        (service_id, property_id, actor_id, actor_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,occurred_at,actor_id) VALUES (%s,%s,10000,'2027-01-01',%s,%s)",
        (current_rate_id, service_id, issue_at - timedelta(seconds=1), actor_id),
    )
    connection.execute(
        "INSERT INTO app.property_service_approval_periods(id,property_service_id,effective_from,"
        "effective_through,approval_reference,approved_at,approved_by,reason) VALUES "
        "(%s,%s,'2027-01-01','2027-12-31','snapshot-approval',%s,%s,'Approved service')",
        (approval_id, service_id, issue_at - timedelta(seconds=1), actor_id),
    )
    connection.execute(
        "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,applicable_from,"
        "applicable_through,service_approval_period_id,terms_reference,recorded_at,recorded_by) "
        "VALUES (%s,%s,%s,'2027-01-01','2027-12-31',%s,'snapshot-term',%s,%s)",
        (term_id, lease_id, service_id, approval_id, issue_at - timedelta(seconds=1), actor_id),
    )
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,due_date,billing_period_start,billing_period_end,"
        "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by) VALUES "
        "(%s,%s,%s,%s,'SERVICE_CHARGES','DRAFT','2027-02-01','2027-02-01','2027-02-01',"
        "'2027-02-28',10000,'GOVERNING_SOURCE','service-snapshot',%s,%s)",
        (invoice_id, f"INV-{invoice_id.hex}", tenant_id, lease_id, actor_id, actor_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,period_start,period_end,source_lease_id,property_service_id,"
        "service_rate_id,lease_service_term_id,service_approval_period_id,"
        "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,created_by) "
        "VALUES (%s,%s,1,'SERVICE_CHARGES','Snapshot Service',10000,'2027-02-01',"
        "'2027-02-28',%s,%s,%s,%s,%s,10000,28,28,%s,%s)",
        (
            line_id,
            invoice_id,
            lease_id,
            service_id,
            current_rate_id,
            term_id,
            approval_id,
            Jsonb({"formula": "monthly_service"}),
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,service_rate_id,"
        "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',"
        "'2027-02-01','2027-02-28',%s,10000,28,28,10000,%s,%s)",
        (
            uuid4(),
            line_id,
            current_rate_id,
            Jsonb({"formula": "monthly_service"}),
            actor_id,
        ),
    )
    future_rate_id = uuid4()
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,occurred_at,actor_id) VALUES (%s,%s,12000,'2027-02-01',%s,%s)",
        (future_rate_id, service_id, issue_at + timedelta(seconds=1), actor_id),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,version=2,"
        "updated_at=%s,updated_by=%s WHERE id=%s",
        (issue_at, actor_id, issue_at, actor_id, invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT line.service_rate_id,component.service_rate_id FROM app.invoice_lines AS line "
        "JOIN app.invoice_line_calculation_components AS component "
        "ON component.invoice_line_id=line.id WHERE line.id=%s",
        (line_id,),
    ).fetchone() == (current_rate_id, current_rate_id)
    with pytest.raises(Error) as involuntary_termination_cannot_invalidate_service:
        with connection.transaction():
            connection.execute(
                "UPDATE app.leases SET status='TERMINATED',terminated_at=%s,"
                "actual_termination_date='2027-02-15',termination_reason='Involuntary',"
                "version=version+1,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (issue_at - timedelta(microseconds=1), actor_id, lease_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert involuntary_termination_cannot_invalidate_service.value.sqlstate == "23514"


def test_adjustment_reversal_and_exceptional_void_preserve_source_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, tenant_id, lease_id = setup_signed_lease(connection)
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct pre-issuance Invoice evidence"
    )
    abandoned_invoice_id = uuid4()
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
        "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
        "current_date,current_date,0,'GOVERNING_SOURCE','abandoned-draft',%s,%s)",
        (
            abandoned_invoice_id,
            f"INV-{abandoned_invoice_id.hex}",
            tenant_id,
            actor_id,
            actor_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    abandoned_row = connection.execute(
        "UPDATE app.invoices SET status='VOID',version=2,"
        "updated_at=GREATEST(statement_timestamp(),created_at),updated_by=%s WHERE id=%s "
        "RETURNING updated_at",
        (actor_id, abandoned_invoice_id),
    ).fetchone()
    assert abandoned_row is not None
    abandoned_at = abandoned_row[0]
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Abandoned incomplete draft',%s,%s,"
        "'invoice.void')",
        (uuid4(), abandoned_invoice_id, abandoned_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status,issued_at,issued_by FROM app.invoices WHERE id=%s", (abandoned_invoice_id,)
    ).fetchone() == ("VOID", None, None)

    fabricated_invoice_id = uuid4()
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
        "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
        "current_date,current_date,0,'GOVERNING_SOURCE','fabricated-issuance',%s,%s)",
        (
            fabricated_invoice_id,
            f"INV-{fabricated_invoice_id.hex}",
            tenant_id,
            actor_id,
            actor_id,
        ),
    )
    with pytest.raises(Error) as abandoned_draft_cannot_fabricate_issuance:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='VOID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, actor_id, fabricated_invoice_id),
            )
    assert abandoned_draft_cannot_fabricate_issuance.value.sqlstate == "55000"

    retained_line_at = datetime.now(UTC) + timedelta(seconds=1)
    with pytest.raises(Error) as abandoned_draft_void_cannot_predate_retained_detail:
        with connection.transaction():
            retained_draft_id, _ = create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_id,
                lease_id=lease_id,
                period_start=date(2027, 11, 1),
                issue=False,
                line_created_at=retained_line_at,
            )
            retained_void_at = retained_line_at - timedelta(microseconds=1)
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=2,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (retained_line_at, actor_id, retained_draft_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Retained detail is later',%s,%s,"
                "'invoice.void')",
                (uuid4(), retained_draft_id, retained_void_at, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert abandoned_draft_void_cannot_predate_retained_detail.value.sqlstate == "23514"

    for terminal_status in ("UNPAID", "VOID"):
        with pytest.raises(Error) as backdated_final_detail:
            with connection.transaction():
                mutated_draft_id, mutated_line_id = create_recurring_rent_invoice(
                    connection,
                    actor_id=actor_id,
                    customer_id=tenant_id,
                    lease_id=lease_id,
                    period_start=date(2027, 12, 1),
                    issue=False,
                )
                connection.execute(
                    "UPDATE app.invoice_lines SET calculation_trace=%s WHERE id=%s",
                    (Jsonb({"formula": "mutated_after_event"}), mutated_line_id),
                )
                connection.execute(
                    "UPDATE app.invoice_line_calculation_components SET calculation_trace=%s "
                    "WHERE invoice_line_id=%s",
                    (Jsonb({"formula": "mutated_after_event"}), mutated_line_id),
                )
                changed_at_row = connection.execute(
                    "SELECT GREATEST(line.last_changed_at,max(component.last_changed_at)) "
                    "FROM app.invoice_lines AS line "
                    "JOIN app.invoice_line_calculation_components AS component "
                    "ON component.invoice_line_id=line.id WHERE line.id=%s "
                    "GROUP BY line.last_changed_at",
                    (mutated_line_id,),
                ).fetchone()
                assert changed_at_row is not None
                assert isinstance(changed_at_row[0], datetime)
                final_event_at = changed_at_row[0] - timedelta(microseconds=1)
                if terminal_status == "UNPAID":
                    connection.execute(
                        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
                        "version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                        (final_event_at, actor_id, actor_id, mutated_draft_id),
                    )
                else:
                    connection.execute(
                        "UPDATE app.invoices SET status='VOID',version=2,"
                        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                        (actor_id, mutated_draft_id),
                    )
                    connection.execute(
                        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                        "actor_id,authorization_reference) VALUES (%s,%s,"
                        "'Backdated after detail mutation',%s,%s,'invoice.void')",
                        (uuid4(), mutated_draft_id, final_event_at, actor_id),
                    )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert backdated_final_detail.value.sqlstate == "23514"

    invoice_id, line_id = create_recurring_rent_invoice(
        connection, actor_id=actor_id, customer_id=tenant_id, lease_id=lease_id
    )
    with pytest.raises(Error) as involuntary_termination_cannot_invalidate_rent:
        with connection.transaction():
            connection.execute(
                "UPDATE app.leases SET status='TERMINATED',"
                "terminated_at=(SELECT issued_at-interval '1 microsecond' "
                "FROM app.invoices WHERE id=%s),actual_termination_date='2027-02-15',"
                "termination_reason='Involuntary',version=version+1,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (invoice_id, actor_id, lease_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert involuntary_termination_cannot_invalidate_rent.value.sqlstate == "23514"
    adjustment_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.invoice_adjustments(
            id,invoice_id,invoice_line_id,adjustment_type,amount_usd_cents,
            source_reference,reason,occurred_at,actor_id,authorization_reference
        ) VALUES (%s,%s,%s,'CREDIT',5000,'approved-correction','Amount correction',
            statement_timestamp(),%s,'invoice.adjust')
        """,
        (adjustment_id, invoice_id, line_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT app.invoice_adjusted_line_obligation(%s)", (line_id,)
    ).fetchone() == (75000,)

    with pytest.raises(Error) as zero_obligation_without_status_reconciliation:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',75000,'zero-obligation',"
                "'Would require a derived status transition',statement_timestamp(),%s,"
                "'invoice.adjust')",
                (uuid4(), invoice_id, line_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert zero_obligation_without_status_reconciliation.value.sqlstate == "23514"
    transient_invoice_id, transient_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 4, 1),
    )
    transient_zero_at = datetime.now(UTC)
    with pytest.raises(Error) as transient_zero_without_status_history:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',80000,'transient-zero',"
                "'Would transiently settle the Invoice',%s,%s,'invoice.adjust')",
                (
                    uuid4(),
                    transient_invoice_id,
                    transient_line_id,
                    transient_zero_at,
                    actor_id,
                ),
            )
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'DEBIT',1,'post-zero-debit',"
                "'Cannot hide the transient settled state',%s,%s,'invoice.adjust')",
                (
                    uuid4(),
                    transient_invoice_id,
                    transient_line_id,
                    transient_zero_at + timedelta(microseconds=1),
                    actor_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert transient_zero_without_status_history.value.sqlstate == "23514"
    paid_invoice_id, paid_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2027, 3, 1),
    )
    paid_adjustment_id = uuid4()
    future_transition_at = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(Error) as paid_transition_before_causal_adjustment:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',80000,'future-full-credit',"
                "'Future-dated authorized full correction',%s,%s,'invoice.adjust')",
                (uuid4(), paid_invoice_id, paid_line_id, future_transition_at, actor_id),
            )
            connection.execute(
                "UPDATE app.invoices SET status='PAID',version=3,updated_at=statement_timestamp(),"
                "updated_by=%s WHERE id=%s",
                (actor_id, paid_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert paid_transition_before_causal_adjustment.value.sqlstate == "23514"
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
        "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
        "VALUES (%s,%s,%s,'CREDIT',80000,'full-credit','Authorized full correction',"
        "statement_timestamp(),%s,'invoice.adjust')",
        (paid_adjustment_id, paid_invoice_id, paid_line_id, actor_id),
    )
    connection.execute(
        "UPDATE app.invoices SET status='PAID',version=3,updated_at=statement_timestamp(),"
        "updated_by=%s WHERE id=%s",
        (actor_id, paid_invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status,app.invoice_adjusted_line_obligation(%s) FROM app.invoices WHERE id=%s",
        (paid_line_id, paid_invoice_id),
    ).fetchone() == ("PAID", 0)
    transient_reopen_at = datetime.now(UTC) + timedelta(seconds=1)
    with pytest.raises(Error) as transient_reopen_without_status_history:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,"
                "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,"
                "'Transiently reopen paid Invoice',%s,%s,'invoice.adjust.reverse')",
                (uuid4(), paid_adjustment_id, transient_reopen_at, actor_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',80000,"
                "'replacement-full-credit','Cannot hide the transient open balance',%s,%s,"
                "'invoice.adjust')",
                (
                    uuid4(),
                    paid_invoice_id,
                    paid_line_id,
                    transient_reopen_at + timedelta(microseconds=1),
                    actor_id,
                ),
            )
            connection.execute(
                "UPDATE app.invoices SET version=4,updated_at=%s,updated_by=%s WHERE id=%s",
                (
                    transient_reopen_at + timedelta(microseconds=1),
                    actor_id,
                    paid_invoice_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert transient_reopen_without_status_history.value.sqlstate == "23514"
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,"
        "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,'Full credit reversed',"
        "statement_timestamp()+interval '1 microsecond',%s,'invoice.adjust.reverse')",
        (uuid4(), paid_adjustment_id, actor_id),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',version=4,"
        "updated_at=statement_timestamp()+interval '1 microsecond',"
        "updated_by=%s WHERE id=%s",
        (actor_id, paid_invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status,app.invoice_adjusted_line_obligation(%s) FROM app.invoices WHERE id=%s",
        (paid_line_id, paid_invoice_id),
    ).fetchone() == ("UNPAID", 80000)
    with pytest.raises(Error) as transient_negative_obligation:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',80000,"
                "'transient-over-credit','Must fail at its own event boundary',"
                "statement_timestamp()+interval '1 second',%s,'invoice.adjust')",
                (uuid4(), invoice_id, line_id, actor_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'DEBIT',80001,"
                "'later-restoration','Cannot hide the earlier invalid balance',"
                "statement_timestamp()+interval '2 seconds',%s,'invoice.adjust')",
                (uuid4(), invoice_id, line_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert transient_negative_obligation.value.sqlstate == "23514"
    with pytest.raises(Error) as backdated_adjustment:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'DEBIT',1,'backdated-adjustment',"
                "'Impossible chronology','2000-01-01T00:00:00Z',%s,'invoice.adjust')",
                (uuid4(), invoice_id, line_id, actor_id),
            )
    assert backdated_adjustment.value.sqlstate == "23514"

    with pytest.raises(Error) as unresolved_void:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Invalid source',now(),%s,'invoice.void')",
                (uuid4(), invoice_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert unresolved_void.value.sqlstate == "23514"

    with pytest.raises(Error) as reversal_before_adjustment:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,"
                "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,"
                "'Impossible chronology','2000-01-01T00:00:00Z',%s,"
                "'invoice.adjust.reverse')",
                (uuid4(), adjustment_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert reversal_before_adjustment.value.sqlstate == "23514"
    reversal_id = uuid4()
    connection.execute(
        "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,occurred_at,"
        "actor_id,authorization_reference) VALUES (%s,%s,'Correction withdrawn',"
        "statement_timestamp()+interval '1 microsecond',%s,"
        "'invoice.adjust.reverse')",
        (reversal_id, adjustment_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as void_before_issuance:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Impossible chronology',"
                "'2000-01-01T00:00:00Z',%s,'invoice.void')",
                (uuid4(), invoice_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_before_issuance.value.sqlstate == "23514"
    with pytest.raises(Error) as void_transition_before_causal_event:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=statement_timestamp()+interval '1 second',updated_by=%s "
                "WHERE id=%s",
                (actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Future causal event',"
                "statement_timestamp()+interval '2 seconds',%s,'invoice.void')",
                (uuid4(), invoice_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_transition_before_causal_event.value.sqlstate == "23514"
    successful_void_at = datetime.now(UTC) + timedelta(seconds=1)
    successful_void_event_id = uuid4()
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (successful_void_at, actor_id, invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Invalid source',%s,%s,'invoice.void')",
        (successful_void_event_id, invoice_id, successful_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone() == ("VOID",)
    with pytest.raises(Error) as issued_void_cannot_erase_issuance:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET issued_at=NULL,issued_by=NULL,version=4,"
                "updated_at=%s,updated_by=%s WHERE id=%s",
                (successful_void_at + timedelta(microseconds=1), actor_id, invoice_id),
            )
    assert issued_void_cannot_erase_issuance.value.sqlstate == "55000"
    assert connection.execute(
        "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", (invoice_id,)
    ).fetchone() == (1,)
    permanent_events = (
        ("invoice_adjustments", adjustment_id),
        ("invoice_adjustment_reversals", reversal_id),
        ("invoice_void_events", successful_void_event_id),
    )
    for table_name, event_id in permanent_events:
        with pytest.raises(Error) as rewrite_permanent_event:
            with connection.transaction():
                connection.execute(
                    f"UPDATE app.{table_name} SET reason='Tampered evidence' WHERE id=%s",
                    (event_id,),
                )
        assert rewrite_permanent_event.value.sqlstate == "55000"
        with pytest.raises(Error) as delete_permanent_event:
            with connection.transaction():
                connection.execute(f"DELETE FROM app.{table_name} WHERE id=%s", (event_id,))
        assert delete_permanent_event.value.sqlstate == "55000"
    with pytest.raises(Error) as truncate_permanent_event_tables:
        with connection.transaction():
            connection.execute(
                "TRUNCATE TABLE app.invoice_adjustment_reversals,"
                "app.invoice_adjustments,app.invoice_void_events"
            )
    assert truncate_permanent_event_tables.value.sqlstate == "55000"
    replacement_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        issue=False,
    )
    with pytest.raises(Error) as replacement_before_void_event:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',"
                "issued_at=(SELECT occurred_at-interval '1 microsecond' "
                "FROM app.invoice_void_events WHERE invoice_id=%s),issued_by=%s,version=2,"
                "updated_at=(SELECT occurred_at-interval '1 microsecond' "
                "FROM app.invoice_void_events WHERE invoice_id=%s),updated_by=%s WHERE id=%s",
                (
                    invoice_id,
                    actor_id,
                    invoice_id,
                    actor_id,
                    replacement_invoice_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert replacement_before_void_event.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',"
        "issued_at=(SELECT occurred_at+interval '1 microsecond' "
        "FROM app.invoice_void_events WHERE invoice_id=%s),issued_by=%s,version=2,"
        "updated_at=(SELECT occurred_at+interval '1 microsecond' "
        "FROM app.invoice_void_events WHERE invoice_id=%s),updated_by=%s WHERE id=%s",
        (invoice_id, actor_id, invoice_id, actor_id, replacement_invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status FROM app.invoices WHERE id=%s", (replacement_invoice_id,)
    ).fetchone() == ("UNPAID",)
    with pytest.raises(Error) as issued_void_cannot_reuse_issuance_timestamp:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=issued_at+interval '1 second',updated_by=%s WHERE id=%s",
                (actor_id, replacement_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) SELECT %s,id,'Backdated to issuance',issued_at,%s,"
                "'invoice.void' FROM app.invoices WHERE id=%s",
                (uuid4(), actor_id, replacement_invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert issued_void_cannot_reuse_issuance_timestamp.value.sqlstate == "23514"


def test_final_late_payment_waiver_and_charge_corrections_are_reconstructable(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, customer_id, lease_id = setup_signed_lease(connection)
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct late-payment source DRAFT detail"
    )
    obligation_id = uuid4()
    invoice_id = uuid4()
    line_id = uuid4()
    due_date = date(2027, 1, 1)
    assessed_at = datetime(2027, 1, 1, 18, 0, tzinfo=UTC)
    issued_at = assessed_at - timedelta(hours=1)
    created_at = issued_at - timedelta(hours=1)
    authorized_at = created_at - timedelta(hours=1)
    connection.execute(
        "INSERT INTO app.authorized_nonrecurring_obligations("
        "id,customer_id,lease_id,category,description,"
        "authorized_amount_usd_cents,governing_due_date,due_date_source,source_reference,"
        "authorized_at,authorized_by,"
        "authorization_reference) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','Approved charge',10000,"
        "%s,'approved-event','approved-event',%s,%s,'invoice.nonrecurring.authorize')",
        (obligation_id, customer_id, lease_id, due_date, authorized_at, actor_id),
    )
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,"
        "due_date,original_total_usd_cents,due_date_rule,due_date_source,created_at,updated_at,"
        "created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',%s,%s,10000,'GOVERNING_SOURCE',"
        "'approved-event',%s,%s,%s,%s)",
        (
            invoice_id,
            f"INV-{invoice_id.hex}",
            customer_id,
            lease_id,
            due_date,
            due_date,
            created_at,
            created_at,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,created_by) "
        "VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES','Approved charge',10000,%s,%s,%s,%s)",
        (
            line_id,
            invoice_id,
            obligation_id,
            Jsonb({"source": "approved-event"}),
            created_at,
            actor_id,
        ),
    )
    unsupported_component_id = uuid4()
    connection.execute(
        "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
        "component_sequence,component_kind,period_start,period_end,amount_usd_cents,"
        "calculation_trace,created_by) VALUES (%s,%s,1,'OTHER_APPROVED_COMPONENT',"
        "'2027-01-01','2027-01-01',10000,%s,%s)",
        (unsupported_component_id, line_id, Jsonb({"source": "not-applicable"}), actor_id),
    )
    with pytest.raises(Error) as unsupported_nonrecurring_component:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
                "version=2,updated_at=%s,updated_by=%s WHERE id=%s",
                (issued_at, actor_id, issued_at, actor_id, invoice_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert unsupported_nonrecurring_component.value.sqlstate == "23514"
    connection.execute(
        "DELETE FROM app.invoice_line_calculation_components WHERE id=%s",
        (unsupported_component_id,),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
        "version=2,updated_at=%s,updated_by=%s WHERE id=%s",
        (issued_at, actor_id, issued_at, actor_id, invoice_id),
    )
    lease_less_obligation_id = uuid4()
    lease_less_invoice_id = uuid4()
    lease_less_line_id = uuid4()
    connection.execute(
        "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,description,"
        "authorized_amount_usd_cents,governing_due_date,due_date_source,source_reference,"
        "authorized_at,authorized_by,"
        "authorization_reference) VALUES (%s,%s,'MISCELLANEOUS_CHARGES',"
        "'Lease-less approved charge',5000,%s,'lease-less-approved-event',"
        "'lease-less-approved-event',%s,%s,"
        "'invoice.nonrecurring.authorize')",
        (lease_less_obligation_id, customer_id, due_date, authorized_at, actor_id),
    )
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
        "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_at,updated_at,created_by,updated_by) VALUES (%s,%s,%s,"
        "'MISCELLANEOUS_CHARGES','DRAFT',%s,%s,5000,'GOVERNING_SOURCE',"
        "'lease-less-approved-event',%s,%s,%s,%s)",
        (
            lease_less_invoice_id,
            f"INV-{lease_less_invoice_id.hex}",
            customer_id,
            due_date,
            due_date,
            created_at,
            created_at,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,created_by) "
        "VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES','Lease-less approved charge',5000,%s,%s,%s,%s)",
        (
            lease_less_line_id,
            lease_less_invoice_id,
            lease_less_obligation_id,
            Jsonb({"source": "lease-less-approved-event"}),
            created_at,
            actor_id,
        ),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,version=2,"
        "updated_at=%s,updated_by=%s WHERE id=%s",
        (issued_at, actor_id, issued_at, actor_id, lease_less_invoice_id),
    )
    with pytest.raises(Error) as lease_less_late_payment:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,"
                "default_rate_basis_points,calculated_default_amount_usd_cents,"
                "decision_outcome,approved_amount_usd_cents,assessed_at,finalized_at,"
                "finalized_by,reason,authorization_reference,calculation_trace) "
                "VALUES (%s,%s,%s,%s,5000,1000,500,'WAIVED',0,%s,%s,%s,"
                "'Not payable under a Lease','late-payment.decide',%s)",
                (
                    uuid4(),
                    lease_less_invoice_id,
                    customer_id,
                    due_date,
                    assessed_at,
                    assessed_at,
                    actor_id,
                    Jsonb({"formula": "10%"}),
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert lease_less_late_payment.value.sqlstate == "23514"
    decision_id = uuid4()
    with pytest.raises(Error) as assessment_before_issuance:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,"
                "default_rate_basis_points,calculated_default_amount_usd_cents,"
                "decision_outcome,approved_amount_usd_cents,assessed_at,finalized_at,"
                "finalized_by,reason,authorization_reference,calculation_trace) "
                "VALUES (%s,%s,%s,%s,10000,1000,1000,'WAIVED',0,%s,%s,%s,"
                "'Backdated assessment','late-payment.decide',%s)",
                (
                    uuid4(),
                    invoice_id,
                    customer_id,
                    due_date,
                    issued_at - timedelta(seconds=1),
                    issued_at - timedelta(seconds=1),
                    actor_id,
                    Jsonb({"formula": "10%"}),
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert assessment_before_issuance.value.sqlstate == "23514"
    with pytest.raises(Error) as adjustment_inserted_before_same_boundary_decision:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'DEBIT',1,"
                "'decision-order-boundary','Inserted before decision at its boundary',"
                "%s,%s,'invoice.adjust')",
                (uuid4(), invoice_id, line_id, assessed_at, actor_id),
            )
            connection.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,"
                "default_rate_basis_points,calculated_default_amount_usd_cents,"
                "decision_outcome,approved_amount_usd_cents,assessed_at,finalized_at,"
                "finalized_by,reason,authorization_reference,calculation_trace) "
                "VALUES (%s,%s,%s,%s,10001,1000,1000,'WAIVED',0,%s,%s,%s,"
                "'Statement-order boundary','late-payment.decide',%s)",
                (
                    uuid4(),
                    invoice_id,
                    customer_id,
                    due_date,
                    assessed_at,
                    assessed_at,
                    actor_id,
                    Jsonb({"formula": "10%"}),
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert adjustment_inserted_before_same_boundary_decision.value.sqlstate == "23514"
    connection.execute(
        """
        INSERT INTO app.late_payment_decisions(
            id,source_invoice_id,customer_id,source_due_date,
            overdue_balance_at_assessment_usd_cents,default_rate_basis_points,
            calculated_default_amount_usd_cents,decision_outcome,approved_amount_usd_cents,
            assessed_at,finalized_at,finalized_by,reason,authorization_reference,calculation_trace
        ) VALUES (%s,%s,%s,%s,10000,1000,1000,'WAIVED',0,%s,%s,%s,
            'Authorized waiver','late-payment.decide',%s)
        """,
        (
            decision_id,
            invoice_id,
            customer_id,
            due_date,
            assessed_at,
            assessed_at,
            actor_id,
            Jsonb({"formula": "10%"}),
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT decision_outcome,approved_amount_usd_cents FROM app.late_payment_decisions "
        "WHERE id=%s",
        (decision_id,),
    ).fetchone() == ("WAIVED", 0)
    with pytest.raises(Error) as void_at_decision_boundary:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (assessed_at, actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Ambiguous decision boundary',%s,%s,"
                "'invoice.void')",
                (uuid4(), invoice_id, assessed_at, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_at_decision_boundary.value.sqlstate == "23514"
    with pytest.raises(Error) as adjustment_at_decision_boundary:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'DEBIT',1,"
                "'decision-boundary-adjustment','Cannot share final decision timestamp',"
                "%s,%s,'invoice.adjust')",
                (uuid4(), invoice_id, line_id, assessed_at, actor_id),
            )
    assert adjustment_at_decision_boundary.value.sqlstate == "23514"
    with pytest.raises(Error) as void_before_waiver_finalization:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (assessed_at - timedelta(minutes=30), actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Backdated before waiver',%s,%s,"
                "'invoice.void')",
                (
                    uuid4(),
                    invoice_id,
                    assessed_at - timedelta(minutes=30),
                    actor_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_before_waiver_finalization.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
        "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
        "VALUES (%s,%s,%s,'DEBIT',1000,'post-assessment-adjustment',"
        "'Recorded after assessment',%s,%s,'invoice.adjust')",
        (uuid4(), invoice_id, line_id, assessed_at + timedelta(hours=1), actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT app.invoice_adjusted_line_obligation_at(%s,%s),"
        "app.invoice_adjusted_line_obligation(%s)",
        (line_id, assessed_at, line_id),
    ).fetchone() == (10000, 11000)
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice_id,)
    ).fetchone() == (0,)
    with pytest.raises(Error) as repeated_decision:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,default_rate_basis_points,"
                "calculated_default_amount_usd_cents,decision_outcome,approved_amount_usd_cents,"
                "assessed_at,finalized_at,finalized_by,reason,authorization_reference,"
                "calculation_trace) "
                "VALUES (%s,%s,%s,%s,10000,1000,1000,'WAIVED',0,%s,%s,%s,'Again',"
                "'late-payment.decide',%s)",
                (
                    uuid4(),
                    invoice_id,
                    customer_id,
                    due_date,
                    assessed_at + timedelta(hours=2),
                    assessed_at + timedelta(hours=2),
                    actor_id,
                    Jsonb({"formula": "10%"}),
                ),
            )
    assert repeated_decision.value.sqlstate == "23505"

    charged_obligation_id = uuid4()
    charged_invoice_id = uuid4()
    charged_line_id = uuid4()
    connection.execute(
        "INSERT INTO app.authorized_nonrecurring_obligations("
        "id,customer_id,lease_id,category,description,"
        "authorized_amount_usd_cents,governing_due_date,due_date_source,source_reference,"
        "authorized_at,authorized_by,"
        "authorization_reference) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES',"
        "'Second approved charge',"
        "20000,%s,'approved-event-two','approved-event-two',%s,%s,"
        "'invoice.nonrecurring.authorize')",
        (charged_obligation_id, customer_id, lease_id, due_date, authorized_at, actor_id),
    )
    connection.execute(
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
        "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,created_at,"
        "updated_at,created_by,updated_by) VALUES (%s,%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
        "%s,%s,20000,'GOVERNING_SOURCE','approved-event-two',%s,%s,%s,%s)",
        (
            charged_invoice_id,
            f"INV-{charged_invoice_id.hex}",
            customer_id,
            lease_id,
            due_date,
            due_date,
            created_at,
            created_at,
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
        "amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,created_by) "
        "VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES','Second approved charge',20000,%s,%s,%s,%s)",
        (
            charged_line_id,
            charged_invoice_id,
            charged_obligation_id,
            Jsonb({"source": "approved-event-two"}),
            created_at,
            actor_id,
        ),
    )
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
        "version=2,updated_at=%s,updated_by=%s WHERE id=%s",
        (issued_at, actor_id, issued_at, actor_id, charged_invoice_id),
    )
    charged_decision_id = uuid4()
    charge_id = uuid4()
    finalized_at = assessed_at
    correction_at = finalized_at + timedelta(hours=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,source_due_date,"
        "overdue_balance_at_assessment_usd_cents,default_rate_basis_points,"
        "calculated_default_amount_usd_cents,decision_outcome,approved_amount_usd_cents,"
        "assessed_at,finalized_at,finalized_by,reason,authorization_reference,calculation_trace) "
        "VALUES (%s,%s,%s,%s,20000,1000,2000,'REDUCED',1500,%s,%s,%s,"
        "'Approved reduced charge','late-payment.decide',%s)",
        (
            charged_decision_id,
            charged_invoice_id,
            customer_id,
            due_date,
            finalized_at,
            finalized_at,
            actor_id,
            Jsonb({"formula": "10%", "default_usd_cents": 2000}),
        ),
    )
    connection.execute(
        "INSERT INTO app.late_payment_charges(id,customer_id,source_invoice_id,"
        "late_payment_decision_id,original_amount_usd_cents,payable_at,created_at,created_by) "
        "VALUES (%s,%s,%s,%s,1500,%s,%s,%s)",
        (
            charge_id,
            customer_id,
            charged_invoice_id,
            charged_decision_id,
            finalized_at,
            finalized_at,
            actor_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as batched_false_correction_snapshots:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',500,'False first snapshot',1000,500,"
                "%s,%s,'late-payment.correct',%s)",
                (
                    uuid4(),
                    charge_id,
                    correction_at + timedelta(minutes=1),
                    actor_id,
                    uuid4(),
                ),
            )
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',500,'False second snapshot',1000,500,"
                "%s,%s,'late-payment.correct',%s)",
                (
                    uuid4(),
                    charge_id,
                    correction_at + timedelta(minutes=2),
                    actor_id,
                    uuid4(),
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert batched_false_correction_snapshots.value.sqlstate == "40001"
    with pytest.raises(Error) as correction_before_charge:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',1,'Impossible chronology',1500,1499,"
                "'2000-01-01T00:00:00Z',%s,'late-payment.correct',%s)",
                (uuid4(), charge_id, actor_id, uuid4()),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert correction_before_charge.value.sqlstate == "23514"
    with pytest.raises(Error) as reduction_to_zero:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',1500,'Must use Charge reversal',"
                "1500,0,%s,%s,'late-payment.correct',%s)",
                (uuid4(), charge_id, correction_at, actor_id, uuid4()),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert reduction_to_zero.value.sqlstate == "23514"
    reduction_id = uuid4()
    reduction_correlation_id = uuid4()
    connection.execute(
        "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
        "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
        "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
        "correlation_id) VALUES (%s,%s,'REDUCTION',500,'Approved correction',1500,1000,"
        "%s,%s,'late-payment.correct',%s)",
        (
            reduction_id,
            charge_id,
            correction_at + timedelta(hours=1),
            actor_id,
            reduction_correlation_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as repeated_correlation:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',500,'Replayed correction',1500,1000,"
                "%s,%s,'late-payment.correct',%s)",
                (
                    uuid4(),
                    charge_id,
                    correction_at + timedelta(hours=1),
                    actor_id,
                    reduction_correlation_id,
                ),
            )
    assert repeated_correlation.value.sqlstate == "23505"
    with pytest.raises(Error) as backdated_charge_correction:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',1,'Backdated correction',1000,999,"
                "%s,%s,'late-payment.correct',%s)",
                (uuid4(), charge_id, correction_at, actor_id, uuid4()),
            )
    assert backdated_charge_correction.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
        "correction_kind,amount_usd_cents,reverses_correction_id,reason,"
        "previous_obligation_usd_cents,resulting_obligation_usd_cents,occurred_at,actor_id,"
        "authorization_reference,correlation_id) VALUES (%s,%s,'REDUCTION_REVERSAL',500,%s,"
        "'Correction reversed',1000,1500,%s,%s,'late-payment.correct',%s)",
        (
            uuid4(),
            charge_id,
            reduction_id,
            correction_at + timedelta(hours=2),
            actor_id,
            uuid4(),
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT correction_kind,previous_obligation_usd_cents,"
        "resulting_obligation_usd_cents FROM app.late_payment_charge_corrections "
        "WHERE late_payment_charge_id=%s ORDER BY correction_kind",
        (charge_id,),
    ).fetchall() == [("REDUCTION", 1500, 1000), ("REDUCTION_REVERSAL", 1000, 1500)]
    with pytest.raises(Error) as partial_charge_reversal:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'CHARGE_REVERSAL',500,'Partial reversal',"
                "1500,1000,%s,%s,'late-payment.reverse',%s)",
                (uuid4(), charge_id, correction_at + timedelta(hours=3), actor_id, uuid4()),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert partial_charge_reversal.value.sqlstate == "23514"
    with pytest.raises(Error) as void_with_active_charge:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=%s,updated_by=%s WHERE id=%s",
                (correction_at + timedelta(hours=4), actor_id, charged_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Charge source invalid',%s,%s,"
                "'invoice.void')",
                (uuid4(), charged_invoice_id, correction_at + timedelta(hours=4), actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_with_active_charge.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
        "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
        "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
        "correlation_id) VALUES (%s,%s,'CHARGE_REVERSAL',1500,'Complete reversal',1500,0,"
        "%s,%s,'late-payment.reverse',%s)",
        (uuid4(), charge_id, correction_at + timedelta(hours=5), actor_id, uuid4()),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as correction_after_reversal:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
                "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
                "correlation_id) VALUES (%s,%s,'REDUCTION',1,'Too late',0,0,%s,%s,"
                "'late-payment.correct',%s)",
                (uuid4(), charge_id, correction_at + timedelta(hours=6), actor_id, uuid4()),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert correction_after_reversal.value.sqlstate == "55000"
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (correction_at + timedelta(hours=7), actor_id, charged_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Charge source invalid',%s,%s,'invoice.void')",
        (uuid4(), charged_invoice_id, correction_at + timedelta(hours=7), actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as change_charge_after_void:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reason,"
                "previous_obligation_usd_cents,resulting_obligation_usd_cents,occurred_at,"
                "actor_id,authorization_reference,correlation_id) VALUES (%s,%s,"
                "'REDUCTION',1,'Cannot change after VOID',0,0,%s,%s,"
                "'late-payment.correct',%s)",
                (uuid4(), charge_id, correction_at + timedelta(hours=8), actor_id, uuid4()),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert change_charge_after_void.value.sqlstate == "23514"


def test_concurrent_duplicate_rent_period_and_billing_run_are_rejected(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, customer_id, lease_id = setup_signed_lease(
            setup, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
        )
        service_actor_id = register_billing_service_principal(
            setup, property_id=property_id, created_by=actor_id
        )
        adjustment_invoice_id, adjustment_line_id = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=date(2027, 4, 1),
        )
        concurrent_void_invoice_id, concurrent_void_line_id = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=date(2027, 5, 1),
        )
        draft_invoice_id, draft_line_id = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=date(2027, 6, 1),
            issue=False,
        )
        draft_component_row = setup.execute(
            "SELECT id FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
            (draft_line_id,),
        ).fetchone()
        assert draft_component_row is not None
        draft_component_id = draft_component_row[0]
        late_invoice_id, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=date(2027, 7, 1),
        )
        late_decision_id = uuid4()
        late_charge_id = uuid4()
        late_assessed_at = datetime(2028, 1, 1, tzinfo=UTC)
        setup.execute("SET CONSTRAINTS ALL DEFERRED")
        setup.execute(
            "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
            "source_due_date,overdue_balance_at_assessment_usd_cents,"
            "default_rate_basis_points,calculated_default_amount_usd_cents,decision_outcome,"
            "approved_amount_usd_cents,assessed_at,finalized_at,finalized_by,reason,"
            "authorization_reference,calculation_trace) VALUES "
            "(%s,%s,%s,'2027-07-05',80000,1000,8000,'CONFIRMED_DEFAULT',8000,%s,%s,%s,"
            "'Concurrent correction source','late-payment.decide',%s)",
            (
                late_decision_id,
                late_invoice_id,
                customer_id,
                late_assessed_at,
                late_assessed_at,
                actor_id,
                Jsonb({"formula": "10%"}),
            ),
        )
        setup.execute(
            "INSERT INTO app.late_payment_charges(id,customer_id,source_invoice_id,"
            "late_payment_decision_id,original_amount_usd_cents,payable_at,created_at,created_by) "
            "VALUES (%s,%s,%s,%s,8000,%s,%s,%s)",
            (
                late_charge_id,
                customer_id,
                late_invoice_id,
                late_decision_id,
                late_assessed_at,
                late_assessed_at,
                actor_id,
            ),
        )
        setup.execute("SET CONSTRAINTS ALL IMMEDIATE")
        invoices = [
            create_recurring_rent_invoice(
                setup,
                actor_id=actor_id,
                customer_id=customer_id,
                lease_id=lease_id,
                create_line=False,
                issue=False,
            )[0]
            for _ in range(2)
        ]
        generated_race_run_id = uuid4()
        generated_race_attempt_id = uuid4()
        setup.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
            "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
            "(%s,%s,'RENT','generated-void-completion-race','2025-10-25','2025-11-01',"
            "'2025-11-30',%s,%s,'RUNNING',statement_timestamp()-interval '2 seconds')",
            (generated_race_run_id, property_id, uuid4(), service_actor_id),
        )
        setup.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,1,statement_timestamp()-interval '1 second','RUNNING')",
            (generated_race_attempt_id, generated_race_run_id),
        )
        generated_race_invoice_id, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=date(2025, 11, 1),
            originating_billing_run_attempt_id=generated_race_attempt_id,
        )
        setup.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
            "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-11-01','2025-11-30',"
            "'GENERATED',%s,statement_timestamp())",
            (
                uuid4(),
                generated_race_run_id,
                generated_race_attempt_id,
                lease_id,
                generated_race_invoice_id,
            ),
        )
        setup.execute("SET CONSTRAINTS ALL IMMEDIATE")
        setup.commit()

    rent_barrier = Barrier(2)

    def insert_rent(invoice_id: UUID) -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                worker.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                worker.execute(
                    "SELECT count(*) FROM app.active_invoice_source_claims "
                    "WHERE category='RENT' AND source_lease_id=%s",
                    (lease_id,),
                ).fetchone()
                rent_barrier.wait()
                worker.execute(
                    "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,"
                    "description,"
                    "amount_usd_cents,period_start,period_end,source_lease_id,"
                    "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,"
                    "created_by) VALUES (%s,%s,1,'RENT','Monthly Rent',80000,'2027-02-01',"
                    "'2027-02-28',%s,80000,28,28,%s,%s)",
                    (
                        uuid4(),
                        invoice_id,
                        lease_id,
                        Jsonb({"formula": "monthly_rent"}),
                        actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        rent_results = list(pool.map(insert_rent, invoices))
    assert sorted(rent_results) == ["23P01", "committed"]

    adjustment_barrier = Barrier(2)

    def insert_credit(index: int) -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                worker.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                worker.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-financial:{adjustment_invoice_id}",),
                ).fetchone()
                adjustment_barrier.wait()
                worker.execute(
                    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                    "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                    "authorization_reference) VALUES (%s,%s,%s,'CREDIT',50000,%s,"
                    "'Concurrent correction',now(),%s,'invoice.adjust')",
                    (
                        uuid4(),
                        adjustment_invoice_id,
                        adjustment_line_id,
                        f"concurrent-correction-{index}",
                        actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        adjustment_results = list(pool.map(insert_credit, (1, 2)))
    assert sorted(adjustment_results) == ["40001", "committed"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT app.invoice_adjusted_line_obligation(%s)", (adjustment_line_id,)
        ).fetchone() == (30000,)

    replay_barrier = Barrier(2)

    def replay_credit(_: int) -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                replay_barrier.wait()
                worker.execute(
                    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                    "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                    "authorization_reference) VALUES (%s,%s,%s,'CREDIT',10000,"
                    "'stable-replay-key','Replay-safe correction',now(),%s,'invoice.adjust')",
                    (uuid4(), adjustment_invoice_id, adjustment_line_id, actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        replay_results = list(pool.map(replay_credit, (1, 2)))
    assert sorted(replay_results) == ["23505", "committed"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT app.invoice_adjusted_line_obligation(%s)", (adjustment_line_id,)
        ).fetchone() == (20000,)

    void_barrier = Barrier(2)

    def void_invoice() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                worker.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                worker.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-financial:{concurrent_void_invoice_id}",),
                ).fetchone()
                void_barrier.wait()
                worker.execute("SET CONSTRAINTS ALL DEFERRED")
                worker.execute(
                    "UPDATE app.invoices SET status='VOID',version=3,"
                    "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                    (actor_id, concurrent_void_invoice_id),
                )
                worker.execute(
                    "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,'Concurrent invalidation',"
                    "now(),%s,'invoice.void')",
                    (uuid4(), concurrent_void_invoice_id, actor_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def adjust_voiding_invoice() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                worker.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                worker.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-financial:{concurrent_void_invoice_id}",),
                ).fetchone()
                void_barrier.wait()
                worker.execute(
                    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                    "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                    "authorization_reference) VALUES (%s,%s,%s,'CREDIT',1000,'void-race',"
                    "'Concurrent correction',now(),%s,'invoice.adjust')",
                    (
                        uuid4(),
                        concurrent_void_invoice_id,
                        concurrent_void_line_id,
                        actor_id,
                    ),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        void_future = pool.submit(void_invoice)
        adjustment_future = pool.submit(adjust_voiding_invoice)
        void_results = [void_future.result(), adjustment_future.result()]
    assert sorted(void_results) == ["40001", "committed"]

    late_correction_barrier = Barrier(2)

    def reduce_late_charge(index: int) -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                worker.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                worker.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"late-charge:{late_charge_id}",),
                ).fetchone()
                late_correction_barrier.wait()
                worker.execute(
                    "INSERT INTO app.late_payment_charge_corrections("
                    "id,late_payment_charge_id,correction_kind,amount_usd_cents,reason,"
                    "previous_obligation_usd_cents,resulting_obligation_usd_cents,occurred_at,"
                    "actor_id,authorization_reference,correlation_id) VALUES "
                    "(%s,%s,'REDUCTION',100,%s,8000,7900,%s,%s,'late-payment.correct',%s)",
                    (
                        uuid4(),
                        late_charge_id,
                        f"Concurrent reduction {index}",
                        late_assessed_at + timedelta(hours=index),
                        actor_id,
                        uuid4(),
                    ),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        late_correction_results = list(pool.map(reduce_late_charge, (1, 2)))
    assert sorted(late_correction_results) == ["40001", "committed"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT original_amount_usd_cents + COALESCE((SELECT sum(CASE correction_kind "
            "WHEN 'REDUCTION' THEN -amount_usd_cents "
            "WHEN 'CHARGE_REVERSAL' THEN -amount_usd_cents ELSE amount_usd_cents END) "
            "FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=charge.id),0) "
            "FROM app.late_payment_charges AS charge WHERE id=%s",
            (late_charge_id,),
        ).fetchone() == (7900,)

    generated_race_barrier = Barrier(2)
    with psycopg.connect(migrated_database_url) as timing_connection:
        generated_race_void_at_row = timing_connection.execute(
            "SELECT statement_timestamp()+interval '1 day'"
        ).fetchone()
    assert generated_race_void_at_row is not None
    assert isinstance(generated_race_void_at_row[0], datetime)
    generated_race_void_at = generated_race_void_at_row[0]

    def complete_generated_race() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                generated_race_barrier.wait()
                worker.execute(
                    "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
                    "completed_at=statement_timestamp() WHERE id=%s",
                    (generated_race_attempt_id,),
                )
                worker.execute(
                    "UPDATE app.billing_runs SET status='SUCCEEDED',"
                    "completed_at=statement_timestamp() WHERE id=%s",
                    (generated_race_run_id,),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def void_generated_race() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                generated_race_barrier.wait()
                worker.execute("SET CONSTRAINTS ALL DEFERRED")
                worker.execute(
                    "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,"
                    "updated_by=%s WHERE id=%s",
                    (generated_race_void_at, actor_id, generated_race_invoice_id),
                )
                worker.execute(
                    "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,"
                    "'Concurrent generated correction',%s,%s,'invoice.void')",
                    (uuid4(), generated_race_invoice_id, generated_race_void_at, actor_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion_future = pool.submit(complete_generated_race)
        generated_void_future = pool.submit(void_generated_race)
        generated_race_results = [completion_future.result(), generated_void_future.result()]
    assert "committed" in generated_race_results
    assert sorted(generated_race_results) in (["23514", "committed"], ["committed", "committed"])
    with psycopg.connect(migrated_database_url) as verify:
        generated_race_state = verify.execute(
            "SELECT invoice.status,void_event.occurred_at,attempt.outcome,attempt.completed_at,"
            "run.status,run.completed_at FROM app.invoices AS invoice "
            "JOIN app.invoice_void_events AS void_event ON void_event.invoice_id=invoice.id "
            "JOIN app.billing_run_attempts AS attempt "
            "ON attempt.id=invoice.originating_billing_run_attempt_id "
            "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
            (generated_race_invoice_id,),
        ).fetchone()
    assert generated_race_state is not None
    assert generated_race_state[0] == "VOID"
    if generated_race_state[4] == "SUCCEEDED":
        assert generated_race_state[2] == "SUCCEEDED"
        assert generated_race_state[5] is not None
        assert generated_race_state[1] > generated_race_state[5]
    else:
        assert generated_race_state[4] == "RUNNING"
        assert generated_race_state[2] == "RUNNING"

    issuance_barrier = Barrier(2)

    def issue_draft() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                issuance_barrier.wait()
                worker.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, actor_id, draft_invoice_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "issued"
        except Error as error:
            return error.sqlstate or "error"

    def delete_draft_component() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                issuance_barrier.wait()
                worker.execute(
                    "DELETE FROM app.invoice_line_calculation_components WHERE id=%s",
                    (draft_component_id,),
                )
            return "deleted"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        issue_future = pool.submit(issue_draft)
        delete_future = pool.submit(delete_draft_component)
        issuance_results = [issue_future.result(), delete_future.result()]
    assert sorted(issuance_results) in (["23514", "deleted"], ["55000", "issued"])
    with psycopg.connect(migrated_database_url) as verify:
        status_row = verify.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (draft_invoice_id,)
        ).fetchone()
        component_count_row = verify.execute(
            "SELECT count(*) FROM app.invoice_line_calculation_components WHERE id=%s",
            (draft_component_id,),
        ).fetchone()
        assert status_row is not None
        assert component_count_row is not None
        status = status_row[0]
        component_count = component_count_row[0]
    assert (status, component_count) in (("DRAFT", 0), ("UNPAID", 1))

    run_barrier = Barrier(2)

    def insert_run(index: int) -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                run_barrier.wait()
                worker.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                    "started_at) VALUES (%s,%s,'RENT',%s,'2025-01-25','2025-02-01',"
                    "'2025-02-28',%s,%s,'RUNNING',now())",
                    (uuid4(), property_id, f"rent-2025-02-{index}", uuid4(), service_actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        run_results = list(pool.map(insert_run, (1, 2)))
    assert sorted(run_results) == ["23505", "committed"]

    overlap_barrier = Barrier(2)

    def insert_overlapping_run(index: int) -> str:
        period_start, period_end = (
            (date(2025, 4, 1), date(2025, 4, 30))
            if index == 1
            else (date(2025, 4, 15), date(2025, 5, 14))
        )
        try:
            with psycopg.connect(migrated_database_url) as worker:
                overlap_barrier.wait()
                worker.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                    "started_at) VALUES (%s,%s,'RENT',%s,'2025-03-25',%s,%s,%s,%s,"
                    "'RUNNING',now())",
                    (
                        uuid4(),
                        property_id,
                        f"overlapping-rent-{index}",
                        period_start,
                        period_end,
                        uuid4(),
                        service_actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        overlap_results = list(pool.map(insert_overlapping_run, (1, 2)))
    assert sorted(overlap_results) == ["23514", "committed"]


def test_concurrent_invoice_issuance_serializes_lease_and_service_sources(
    migrated_database_url: str,
) -> None:
    current_day = date.today()
    lease_start = current_day.replace(day=1)
    period_start = (lease_start + timedelta(days=32)).replace(day=1)
    period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
        days=1
    )
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        lease_id = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=lease_start,
            end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
        )
        sign_lease(setup, lease_id, actor_id)
        lease_invoice_id, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=tenant_id,
            lease_id=lease_id,
            period_start=period_start,
            issue=False,
        )
        lease_version_row = setup.execute(
            "SELECT version FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone()
        assert lease_version_row is not None
        lease_version = lease_version_row[0]

    termination_ready = Event()
    issuance_started = Event()

    def terminate_before_issuance() -> str:
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute(
                    "SELECT app.terminate_lease(%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),"
                    "'BR-LEASE-021','Concurrent termination',%s)",
                    (
                        property_id,
                        uuid4(),
                        "b" * 64,
                        uuid4(),
                        lease_id,
                        lease_version,
                        current_day,
                        actor_id,
                    ),
                )
                termination_ready.set()
                assert issuance_started.wait(timeout=10)
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def issue_after_termination_started() -> str:
        assert termination_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as issuer:
                issuer.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                issuer.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-lease:{lease_id}",),
                ).fetchone()
                issuance_started.set()
                issuer.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, actor_id, lease_invoice_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        termination_future = pool.submit(terminate_before_issuance)
        issuance_future = pool.submit(issue_after_termination_started)
        assert termination_future.result(timeout=20) == "committed"
        assert issuance_future.result(timeout=20) == "40001"

    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        service_lease_id = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=lease_start,
            end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
        )
        sign_lease(setup, service_lease_id, actor_id)
        service_id = uuid4()
        current_rate_id = uuid4()
        approval_id = uuid4()
        term_id = uuid4()
        service_invoice_id = uuid4()
        service_line_id = uuid4()
        setup.execute(
            "INSERT INTO app.property_services(id,property_id,service_code,display_name,"
            "configured_by,created_by,updated_by) VALUES (%s,%s,'CONCURRENT',"
            "'Concurrent Service',%s,%s,%s)",
            (service_id, property_id, actor_id, actor_id, actor_id),
        )
        setup.execute(
            "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
            "effective_date,occurred_at,actor_id) VALUES (%s,%s,10000,%s,"
            "statement_timestamp(),%s)",
            (current_rate_id, service_id, period_start - timedelta(days=1), actor_id),
        )
        setup.execute(
            "INSERT INTO app.property_service_approval_periods(id,property_service_id,"
            "effective_from,effective_through,approval_reference,approved_at,approved_by,"
            "reason) VALUES (%s,%s,%s,%s,'concurrent-approval',statement_timestamp(),%s,"
            "'Concurrent approval')",
            (approval_id, service_id, period_start, period_end, actor_id),
        )
        setup.execute(
            "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,"
            "applicable_from,applicable_through,service_approval_period_id,terms_reference,"
            "recorded_at,recorded_by) VALUES (%s,%s,%s,%s,%s,%s,'concurrent-term',"
            "statement_timestamp(),%s)",
            (
                term_id,
                service_lease_id,
                service_id,
                period_start,
                period_end,
                approval_id,
                actor_id,
            ),
        )
        setup.execute(
            "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,"
            "status,invoice_date,due_date,billing_period_start,billing_period_end,"
            "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by) "
            "VALUES (%s,%s,%s,%s,'SERVICE_CHARGES','DRAFT',%s,%s,%s,%s,10000,"
            "'GOVERNING_SOURCE','concurrent-service',%s,%s)",
            (
                service_invoice_id,
                f"INV-{service_invoice_id.hex}",
                tenant_id,
                service_lease_id,
                period_start,
                period_start,
                period_start,
                period_end,
                actor_id,
                actor_id,
            ),
        )
        setup.execute(
            "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
            "amount_usd_cents,period_start,period_end,source_lease_id,property_service_id,"
            "service_rate_id,lease_service_term_id,service_approval_period_id,"
            "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,"
            "created_by) VALUES (%s,%s,1,'SERVICE_CHARGES','Concurrent Service',10000,"
            "%s,%s,%s,%s,%s,%s,%s,10000,%s,%s,%s,%s)",
            (
                service_line_id,
                service_invoice_id,
                period_start,
                period_end,
                service_lease_id,
                service_id,
                current_rate_id,
                term_id,
                approval_id,
                period_end.day,
                period_end.day,
                Jsonb({"formula": "monthly_service"}),
                actor_id,
            ),
        )
        setup.execute(
            "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
            "component_sequence,component_kind,period_start,period_end,service_rate_id,"
            "service_monthly_rate_usd_cents,billable_days,calendar_days,amount_usd_cents,"
            "calculation_trace,created_by) VALUES (%s,%s,1,'FULL_RECURRING_MONTH',%s,%s,"
            "%s,10000,%s,%s,10000,%s,%s)",
            (
                uuid4(),
                service_line_id,
                period_start,
                period_end,
                current_rate_id,
                period_end.day,
                period_end.day,
                Jsonb({"formula": "monthly_service"}),
                actor_id,
            ),
        )

    issue_at = datetime.now(UTC) + timedelta(seconds=1)
    invoice_ready = Event()
    rate_insert_started = Event()

    def issue_before_retroactive_rate() -> str:
        try:
            with psycopg.connect(migrated_database_url) as issuer:
                issuer.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,"
                    "version=2,updated_at=%s,updated_by=%s WHERE id=%s",
                    (issue_at, actor_id, issue_at, actor_id, service_invoice_id),
                )
                invoice_ready.set()
                assert rate_insert_started.wait(timeout=10)
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def insert_retroactive_rate_after_issuance_started() -> str:
        assert invoice_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                writer.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-service:{service_id}",),
                ).fetchone()
                rate_insert_started.set()
                writer.execute(
                    "INSERT INTO app.service_rates(id,property_service_id,"
                    "monthly_rate_usd_cents,effective_date,occurred_at,actor_id) "
                    "VALUES (%s,%s,12000,%s,%s,%s)",
                    (
                        uuid4(),
                        service_id,
                        period_start,
                        issue_at - timedelta(microseconds=1),
                        actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        invoice_future = pool.submit(issue_before_retroactive_rate)
        rate_future = pool.submit(insert_retroactive_rate_after_issuance_started)
        assert invoice_future.result(timeout=20) == "committed"
        assert rate_future.result(timeout=20) == "40001"

    with psycopg.connect(migrated_database_url) as setup:
        actor_id, _, unit_id, tenant_id, other_tenant_id = setup_sources(setup)
        set_draft_correction_context(
            setup, actor_id=actor_id, reason="Correct Initial Rent Occupancy source"
        )
        initial_lease_id = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2036, 1, 1),
            end_date=date(2036, 12, 31),
        )
        sign_lease(setup, initial_lease_id, actor_id)
        source_occupancy_id = uuid4()
        mismatched_occupancy_id = uuid4()
        setup.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,move_out_date,"
            "created_by,updated_by) VALUES (%s,%s,%s,'2036-02-01',NULL,%s,%s),"
            "(%s,%s,%s,'2036-02-01','2036-02-01',%s,%s)",
            (
                source_occupancy_id,
                initial_lease_id,
                tenant_id,
                actor_id,
                actor_id,
                mismatched_occupancy_id,
                initial_lease_id,
                other_tenant_id,
                actor_id,
                actor_id,
            ),
        )
        initial_invoice_id = uuid4()
        initial_line_id = uuid4()
        setup.execute("SET CONSTRAINTS ALL DEFERRED")
        setup.execute(
            "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
            "source_occupancy_id,primary_category,status,invoice_date,due_date,"
            "billing_period_start,billing_period_end,rent_billing_kind,"
            "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by) "
            "VALUES (%s,%s,%s,%s,%s,'RENT','DRAFT','2036-02-01','2036-02-08',"
            "'2036-02-01','2036-02-29','INITIAL',80000,'INITIAL_RENT_SEVEN_DAYS',"
            "'BR-RENT-017',%s,%s)",
            (
                initial_invoice_id,
                f"INV-{initial_invoice_id.hex}",
                tenant_id,
                initial_lease_id,
                mismatched_occupancy_id,
                actor_id,
                actor_id,
            ),
        )
        setup.execute(
            "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
            "amount_usd_cents,period_start,period_end,source_lease_id,"
            "contractual_monthly_usd_cents,billable_days,calendar_days,calculation_trace,"
            "created_by) VALUES (%s,%s,1,'RENT','Initial Rent',80000,'2036-02-01',"
            "'2036-02-29',%s,80000,29,29,%s,%s)",
            (
                initial_line_id,
                initial_invoice_id,
                initial_lease_id,
                Jsonb({"formula": "initial_full_month"}),
                actor_id,
            ),
        )
        setup.execute(
            "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
            "component_sequence,component_kind,period_start,period_end,"
            "contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,"
            "calculation_trace,created_by) VALUES (%s,%s,1,'PRORATED_MOVE_IN_MONTH',"
            "'2036-02-01','2036-02-29',80000,29,29,80000,%s,%s)",
            (uuid4(), initial_line_id, Jsonb({"formula": "initial_full_month"}), actor_id),
        )
        with pytest.raises(Error) as mismatched_occupancy_customer:
            with setup.transaction():
                setup.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, actor_id, initial_invoice_id),
                )
                setup.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert mismatched_occupancy_customer.value.sqlstate == "23514"
        setup.execute(
            "UPDATE app.invoices SET source_occupancy_id=%s,version=2,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (source_occupancy_id, actor_id, initial_invoice_id),
        )

    initial_ready = Event()
    occupancy_started = Event()

    def issue_before_backdated_occupancy() -> str:
        try:
            with psycopg.connect(migrated_database_url) as issuer:
                issuer.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=3,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, actor_id, initial_invoice_id),
                )
                initial_ready.set()
                assert occupancy_started.wait(timeout=10)
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def insert_backdated_occupancy_after_issuance_started() -> str:
        assert initial_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                writer.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-lease:{initial_lease_id}",),
                ).fetchone()
                occupancy_started.set()
                writer.execute(
                    "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                    "created_by,updated_by) VALUES (%s,%s,%s,'2036-01-15',%s,%s)",
                    (uuid4(), initial_lease_id, tenant_id, actor_id, actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        issue_future = pool.submit(issue_before_backdated_occupancy)
        occupancy_future = pool.submit(insert_backdated_occupancy_after_issuance_started)
        assert issue_future.result(timeout=20) == "committed"
        assert occupancy_future.result(timeout=20) == "40001"
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT source_occupancy_id FROM app.invoices WHERE id=%s",
            (initial_invoice_id,),
        ).fetchone() == (source_occupancy_id,)
        with pytest.raises(Error) as rewrite_initial_source_move_in_date:
            with verify.transaction():
                verify.execute(
                    "UPDATE app.occupancies SET move_in_date='2036-01-31' WHERE id=%s",
                    (source_occupancy_id,),
                )
        assert rewrite_initial_source_move_in_date.value.sqlstate == "23514"
        with pytest.raises(Error) as reassign_initial_source_lease:
            with verify.transaction():
                verify.execute(
                    "UPDATE app.occupancies SET lease_id=%s WHERE id=%s",
                    (uuid4(), source_occupancy_id),
                )
        assert reassign_initial_source_lease.value.sqlstate == "23514"
        with pytest.raises(Error) as reassign_initial_source_customer:
            with verify.transaction():
                verify.execute(
                    "UPDATE app.occupancies SET customer_id=%s,move_out_date='2036-12-31',"
                    "version=version+1,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (other_tenant_id, actor_id, source_occupancy_id),
                )
        assert reassign_initial_source_customer.value.sqlstate == "23514"
        later_occupancy_id = uuid4()
        verify.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,"
            "updated_by) VALUES (%s,%s,%s,'2036-03-01',%s,%s)",
            (later_occupancy_id, initial_lease_id, other_tenant_id, actor_id, actor_id),
        )
        with pytest.raises(Error) as move_different_occupancy_before_issued_source:
            with verify.transaction():
                verify.execute(
                    "UPDATE app.occupancies SET move_in_date='2036-01-15' WHERE id=%s",
                    (later_occupancy_id,),
                )
        assert move_different_occupancy_before_issued_source.value.sqlstate == "23514"

    with psycopg.connect(migrated_database_url) as setup:
        snapshot_actor_id, snapshot_property_id, snapshot_unit_id, snapshot_tenant_id, _ = (
            setup_sources(setup)
        )
        snapshot_service_actor_id = register_billing_service_principal(
            setup, property_id=snapshot_property_id, created_by=snapshot_actor_id
        )
        snapshot_lease_id = create_draft(
            setup,
            actor_id=snapshot_actor_id,
            unit_id=snapshot_unit_id,
            primary_tenant_id=snapshot_tenant_id,
            start_date=date(2039, 11, 1),
            end_date=date(2040, 12, 31),
        )
    snapshot_run_id = uuid4()
    signing_ready = Event()
    run_insert_started = Event()

    def sign_before_snapshot_materialization() -> str:
        try:
            with psycopg.connect(migrated_database_url) as signer:
                signer.execute(
                    "UPDATE app.leases SET status='SIGNED',signed_at=statement_timestamp(),"
                    "version=version+1,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (snapshot_actor_id, snapshot_lease_id),
                )
                signer.execute(
                    "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                    "created_by,updated_by) VALUES (%s,%s,%s,'2039-11-01',%s,%s)",
                    (
                        uuid4(),
                        snapshot_lease_id,
                        snapshot_tenant_id,
                        snapshot_actor_id,
                        snapshot_actor_id,
                    ),
                )
                signer.execute("SET CONSTRAINTS ALL IMMEDIATE")
                signing_ready.set()
                assert run_insert_started.wait(timeout=10)
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def create_run_after_signing_started() -> str:
        assert signing_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as runner:
                runner.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                runner.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"billing-run-eligibility:{snapshot_property_id}",),
                ).fetchone()
                run_insert_started.set()
                runner.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                    "started_at) VALUES (%s,%s,'RENT','concurrent-eligibility-snapshot',"
                    "'2039-12-25','2040-01-01','2040-01-31',%s,%s,'RUNNING',"
                    "TIMESTAMPTZ '2039-12-25 12:00:00+07')",
                    (snapshot_run_id, snapshot_property_id, uuid4(), snapshot_service_actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        sign_future = pool.submit(sign_before_snapshot_materialization)
        run_future = pool.submit(create_run_after_signing_started)
        assert sign_future.result(timeout=20) == "committed"
        assert run_future.result(timeout=20) == "40001"
    retry_run_id = uuid4()
    with psycopg.connect(migrated_database_url) as retry:
        retry.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
            "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
            "started_at) VALUES (%s,%s,'RENT','eligibility-snapshot-retry',"
            "'2039-12-25','2040-01-01','2040-01-31',%s,%s,'RUNNING',"
            "TIMESTAMPTZ '2039-12-25 12:00:00+07')",
            (retry_run_id, snapshot_property_id, uuid4(), snapshot_service_actor_id),
        )
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT source_id FROM app.billing_run_eligible_sources WHERE billing_run_id=%s",
            (retry_run_id,),
        ).fetchall() == [(snapshot_lease_id,)]

    with psycopg.connect(migrated_database_url) as setup:
        occupancy_actor_id, occupancy_property_id, occupancy_unit_id, occupancy_tenant_id, _ = (
            setup_sources(setup)
        )
        occupancy_service_actor_id = register_billing_service_principal(
            setup, property_id=occupancy_property_id, created_by=occupancy_actor_id
        )
        occupancy_lease_id = create_draft(
            setup,
            actor_id=occupancy_actor_id,
            unit_id=occupancy_unit_id,
            primary_tenant_id=occupancy_tenant_id,
            start_date=date(2041, 1, 1),
            end_date=date(2042, 12, 31),
        )
        sign_lease(setup, occupancy_lease_id, occupancy_actor_id)
    occupancy_run_id = uuid4()
    occupancy_snapshot_ready = Event()
    occupancy_committed = Event()

    def create_run_from_pre_occupancy_snapshot() -> str:
        try:
            with psycopg.connect(migrated_database_url) as runner:
                runner.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                runner.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"billing-run-eligibility:{occupancy_property_id}",),
                ).fetchone()
                occupancy_snapshot_ready.set()
                assert occupancy_committed.wait(timeout=10)
                runner.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                    "started_at) VALUES (%s,%s,'RENT','occupancy-only-stale-snapshot',"
                    "'2041-01-25','2041-02-01','2041-02-28',%s,%s,'RUNNING',"
                    "TIMESTAMPTZ '2041-01-25 12:00:00+07')",
                    (
                        occupancy_run_id,
                        occupancy_property_id,
                        uuid4(),
                        occupancy_service_actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def add_occupancy_without_lease_change() -> str:
        assert occupancy_snapshot_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute(
                    "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                    "created_by,updated_by) VALUES (%s,%s,%s,'2041-01-01',%s,%s)",
                    (
                        uuid4(),
                        occupancy_lease_id,
                        occupancy_tenant_id,
                        occupancy_actor_id,
                        occupancy_actor_id,
                    ),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"
        finally:
            occupancy_committed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_run_future = pool.submit(create_run_from_pre_occupancy_snapshot)
        occupancy_future = pool.submit(add_occupancy_without_lease_change)
        assert occupancy_future.result(timeout=20) == "committed"
        assert stale_run_future.result(timeout=20) == "40001"
    occupancy_retry_run_id = uuid4()
    with psycopg.connect(migrated_database_url) as retry:
        retry.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
            "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
            "started_at) VALUES (%s,%s,'RENT','occupancy-only-snapshot-retry',"
            "'2041-01-25','2041-02-01','2041-02-28',%s,%s,'RUNNING',"
            "TIMESTAMPTZ '2041-01-25 12:00:01+07')",
            (
                occupancy_retry_run_id,
                occupancy_property_id,
                uuid4(),
                occupancy_service_actor_id,
            ),
        )
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT source_id FROM app.billing_run_eligible_sources WHERE billing_run_id=%s",
            (occupancy_retry_run_id,),
        ).fetchall() == [(occupancy_lease_id,)]


def test_nonrecurring_obligation_issue_and_void_are_repeatable_read_serialized(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, _, _, _, customer_id = setup_sources(setup)
        obligation_id = uuid4()
        setup.execute(
            "INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,category,"
            "description,authorized_amount_usd_cents,governing_due_date,due_date_source,"
            "source_reference,authorized_at,authorized_by,authorization_reference) VALUES "
            "(%s,%s,'MISCELLANEOUS_CHARGES','Serialized key replacement',2500,"
            "current_date+7,'serialized-obligation','serialized-obligation',"
            "statement_timestamp(),%s,'invoice.nonrecurring.authorize')",
            (obligation_id, customer_id, actor_id),
        )

        def create_draft_obligation_invoice(
            database: Connection[tuple[object, ...]], *, create_line: bool = True
        ) -> UUID:
            invoice_id = uuid4()
            database.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "current_date,current_date+7,2500,'GOVERNING_SOURCE',"
                "'serialized-obligation',%s,%s)",
                (invoice_id, f"INV-{invoice_id.hex}", customer_id, actor_id, actor_id),
            )
            if create_line:
                database.execute(
                    "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,"
                    "description,amount_usd_cents,authorized_obligation_id,calculation_trace,"
                    "created_by) VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES',"
                    "'Serialized key replacement',2500,%s,%s,%s)",
                    (
                        uuid4(),
                        invoice_id,
                        obligation_id,
                        Jsonb({"source": "serialized_obligation"}),
                        actor_id,
                    ),
                )
            return invoice_id

        stale_invoice_id = create_draft_obligation_invoice(setup, create_line=False)
    transient_invoice_id: UUID | None = None

    snapshot_ready = Event()
    void_committed = Event()

    def stale_repeatable_read_issuer() -> str:
        try:
            with psycopg.connect(migrated_database_url) as issuer:
                issuer.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                guard_row = issuer.execute(
                    "SELECT revision FROM app.invoice_serialization_guards WHERE guard_key=%s",
                    (f"invoice-obligation:{obligation_id}",),
                ).fetchone()
                assert guard_row is not None
                snapshot_ready.set()
                assert void_committed.wait(timeout=10)
                issuer.execute(
                    "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,"
                    "description,amount_usd_cents,authorized_obligation_id,calculation_trace,"
                    "created_by) VALUES (%s,%s,1,'MISCELLANEOUS_CHARGES',"
                    "'Serialized key replacement',2500,%s,%s,%s)",
                    (
                        uuid4(),
                        stale_invoice_id,
                        obligation_id,
                        Jsonb({"source": "serialized_obligation"}),
                        actor_id,
                    ),
                )
                issuer.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, actor_id, stale_invoice_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def create_and_void_invisible_active_claim() -> str:
        nonlocal transient_invoice_id
        assert snapshot_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute("SET CONSTRAINTS ALL DEFERRED")
                transient_invoice_id = create_draft_obligation_invoice(writer)
                issue_row = writer.execute(
                    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                    "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s RETURNING issued_at",
                    (actor_id, actor_id, transient_invoice_id),
                ).fetchone()
                assert issue_row is not None
                assert isinstance(issue_row[0], datetime)
                void_at = issue_row[0] + timedelta(microseconds=1)
                writer.execute(
                    "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                    "WHERE id=%s",
                    (void_at, actor_id, transient_invoice_id),
                )
                writer.execute(
                    "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,"
                    "'Same-transaction source correction',%s,%s,'invoice.void')",
                    (uuid4(), transient_invoice_id, void_at, actor_id),
                )
                writer.execute("SET CONSTRAINTS ALL IMMEDIATE")
            void_committed.set()
            return "committed"
        except Error as error:
            void_committed.set()
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_future = pool.submit(stale_repeatable_read_issuer)
        void_future = pool.submit(create_and_void_invisible_active_claim)
        assert void_future.result(timeout=20) == "committed"
        assert stale_future.result(timeout=20) == "40001"

    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (stale_invoice_id,)
        ).fetchone() == ("DRAFT",)
        assert transient_invoice_id is not None
        assert verify.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (transient_invoice_id,)
        ).fetchone() == ("VOID",)
        assert verify.execute(
            "SELECT count(*) FROM app.active_invoice_source_claims "
            "WHERE authorized_obligation_id=%s",
            (obligation_id,),
        ).fetchone() == (0,)


def test_billing_service_identity_schedule_skip_and_failed_run_successor(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, tenant_id, lease_id = setup_signed_lease(
        connection, start_date=date(2049, 12, 1), end_date=date(2050, 12, 31)
    )
    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )

    def insert_run(
        *,
        run_id: UUID,
        business_date: date,
        period_start: date,
        period_end: date,
        system_actor_id: UUID,
        logical_key: str,
        started_at: datetime,
        predecessor_run_id: UUID | None = None,
        target_property_id: UUID = property_id,
    ) -> None:
        connection.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
            "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
            "started_at,predecessor_run_id) VALUES (%s,%s,'RENT',%s,%s,%s,%s,%s,%s,"
            "'RUNNING',%s,%s)",
            (
                run_id,
                target_property_id,
                logical_key,
                business_date,
                period_start,
                period_end,
                uuid4(),
                system_actor_id,
                started_at,
                predecessor_run_id,
            ),
        )

    with pytest.raises(Error) as human_identity_cannot_run_billing:
        with connection.transaction():
            insert_run(
                run_id=uuid4(),
                business_date=date(2049, 11, 25),
                period_start=date(2049, 12, 1),
                period_end=date(2049, 12, 31),
                system_actor_id=actor_id,
                logical_key="human-principal-rejected",
                started_at=datetime(2049, 11, 25, 5, tzinfo=UTC),
            )
    assert human_identity_cannot_run_billing.value.sqlstate == "55000"

    other_property_id = uuid4()
    with pytest.raises(Error) as cross_property_service_identity:
        with connection.transaction():
            insert_run(
                run_id=uuid4(),
                business_date=date(2049, 11, 25),
                period_start=date(2049, 12, 1),
                period_end=date(2049, 12, 31),
                system_actor_id=service_actor_id,
                logical_key="cross-property-principal-rejected",
                started_at=datetime(2049, 11, 25, 5, tzinfo=UTC),
                target_property_id=other_property_id,
            )
    assert cross_property_service_identity.value.sqlstate == "55000"

    disabled_service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )
    connection.execute(
        "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
        "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
        (actor_id, disabled_service_actor_id),
    )
    with pytest.raises(Error) as disabled_service_identity:
        with connection.transaction():
            insert_run(
                run_id=uuid4(),
                business_date=date(2049, 11, 25),
                period_start=date(2049, 12, 1),
                period_end=date(2049, 12, 31),
                system_actor_id=disabled_service_actor_id,
                logical_key="disabled-principal-rejected",
                started_at=datetime(2049, 11, 25, 5, tzinfo=UTC),
            )
    assert disabled_service_identity.value.sqlstate == "55000"

    revalidated_service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )
    revalidation_run_id = uuid4()
    insert_run(
        run_id=revalidation_run_id,
        business_date=date(2050, 12, 25),
        period_start=date(2051, 1, 1),
        period_end=date(2051, 1, 31),
        system_actor_id=revalidated_service_actor_id,
        logical_key="principal-revalidated-at-attempt",
        started_at=datetime(2050, 12, 25, 5, tzinfo=UTC),
    )
    revalidation_attempt_id = uuid4()
    revalidation_started_at = datetime(2050, 12, 25, 5, 0, 1, tzinfo=UTC)
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,"
        "started_at,outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (revalidation_attempt_id, revalidation_run_id, revalidation_started_at),
    )
    with pytest.raises(Error) as disable_cannot_strand_running_evidence:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
                "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
                (actor_id, revalidated_service_actor_id),
            )
    assert disable_cannot_strand_running_evidence.value.sqlstate == "55000"
    revalidation_completed_at = revalidation_started_at + timedelta(seconds=1)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
        "diagnostic_code='principal-retirement' WHERE id=%s",
        (revalidation_completed_at, revalidation_attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='FAILED',completed_at=%s,"
        "failure_code='principal-retirement' WHERE id=%s",
        (revalidation_completed_at, revalidation_run_id),
    )
    connection.execute(
        "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
        "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
        (actor_id, revalidated_service_actor_id),
    )
    assert connection.execute(
        "SELECT lifecycle_state FROM app.billing_service_principals WHERE actor_id=%s",
        (revalidated_service_actor_id,),
    ).fetchone() == ("disabled",)

    for business_date, period_start, period_end, started_at in (
        (
            date(2049, 10, 24),
            date(2049, 11, 1),
            date(2049, 11, 30),
            datetime(2049, 10, 24, 5, tzinfo=UTC),
        ),
        (
            date(2049, 10, 25),
            date(2049, 12, 1),
            date(2049, 12, 31),
            datetime(2049, 10, 25, 5, tzinfo=UTC),
        ),
        (
            date(2049, 10, 25),
            date(2049, 11, 1),
            date(2049, 11, 30),
            datetime(2049, 10, 24, 5, tzinfo=UTC),
        ),
    ):
        with pytest.raises(Error) as invalid_schedule:
            with connection.transaction():
                insert_run(
                    run_id=uuid4(),
                    business_date=business_date,
                    period_start=period_start,
                    period_end=period_end,
                    system_actor_id=service_actor_id,
                    logical_key=f"invalid-schedule-{uuid4().hex}",
                    started_at=started_at,
                )
        assert invalid_schedule.value.sqlstate == "23514"

    generated_run_id = uuid4()
    generated_attempt_id = uuid4()
    generated_started_at = datetime(2049, 12, 25, 5, tzinfo=UTC)
    insert_run(
        run_id=generated_run_id,
        business_date=date(2049, 12, 25),
        period_start=date(2050, 1, 1),
        period_end=date(2050, 1, 31),
        system_actor_id=service_actor_id,
        logical_key="canonical-scheduled-rent",
        started_at=generated_started_at,
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (generated_attempt_id, generated_run_id, generated_started_at),
    )
    generated_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2050, 1, 1),
        originating_billing_run_attempt_id=generated_attempt_id,
    )
    assert connection.execute(
        "SELECT invoice_date,billing_period_start,billing_period_end,created_by,issued_by "
        "FROM app.invoices WHERE id=%s",
        (generated_invoice_id,),
    ).fetchone() == (
        date(2049, 12, 25),
        date(2050, 1, 1),
        date(2050, 1, 31),
        service_actor_id,
        service_actor_id,
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
        "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2050-01-01','2050-01-31',"
        "'GENERATED',%s,%s)",
        (
            uuid4(),
            generated_run_id,
            generated_attempt_id,
            lease_id,
            generated_invoice_id,
            generated_started_at + timedelta(seconds=1),
        ),
    )
    with pytest.raises(Error) as skipped_without_evidence:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,"
                "'2050-01-01','2050-01-31','SKIPPED',NULL,"
                "'ACTIVE_INVOICE_ALREADY_EXISTS',%s)",
                (
                    uuid4(),
                    generated_run_id,
                    generated_attempt_id,
                    lease_id,
                    generated_started_at + timedelta(seconds=2),
                ),
            )
    assert skipped_without_evidence.value.sqlstate == "23514"
    with pytest.raises(Error) as skipped_without_reason:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2050-01-01','2050-01-30',"
                "'SKIPPED',%s,%s)",
                (
                    uuid4(),
                    generated_run_id,
                    generated_attempt_id,
                    lease_id,
                    generated_invoice_id,
                    generated_started_at + timedelta(seconds=2),
                ),
            )
    assert skipped_without_reason.value.sqlstate == "55000"

    failed_run_id = uuid4()
    failed_attempt_id = uuid4()
    failed_started_at = datetime(2054, 12, 25, 5, tzinfo=UTC)
    insert_run(
        run_id=failed_run_id,
        business_date=date(2054, 12, 25),
        period_start=date(2055, 1, 1),
        period_end=date(2055, 1, 31),
        system_actor_id=service_actor_id,
        logical_key="failed-root-run",
        started_at=failed_started_at,
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (failed_attempt_id, failed_run_id, failed_started_at),
    )
    failed_completed_at = failed_started_at + timedelta(seconds=1)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
        "diagnostic_code='bounded-provider-failure' WHERE id=%s",
        (failed_completed_at, failed_attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='FAILED',completed_at=%s,"
        "failure_code='bounded-provider-failure' WHERE id=%s",
        (failed_completed_at + timedelta(microseconds=1), failed_run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as unrelated_root_cannot_replace_failed_run:
        with connection.transaction():
            insert_run(
                run_id=uuid4(),
                business_date=date(2054, 12, 25),
                period_start=date(2055, 1, 1),
                period_end=date(2055, 1, 31),
                system_actor_id=service_actor_id,
                logical_key="unrelated-root-retry",
                started_at=failed_completed_at + timedelta(seconds=1),
            )
    assert unrelated_root_cannot_replace_failed_run.value.sqlstate == "23505"

    successor_run_id = uuid4()
    insert_run(
        run_id=successor_run_id,
        business_date=date(2054, 12, 25),
        period_start=date(2055, 1, 1),
        period_end=date(2055, 1, 31),
        system_actor_id=service_actor_id,
        logical_key="failed-root-successor",
        started_at=failed_completed_at + timedelta(seconds=1),
        predecessor_run_id=failed_run_id,
    )
    assert connection.execute(
        "SELECT predecessor_run_id FROM app.billing_runs WHERE id=%s", (successor_run_id,)
    ).fetchone() == (failed_run_id,)
    assert connection.execute(
        "SELECT NOT EXISTS ((SELECT source_kind,source_id,source_period_start,source_period_end "
        "FROM app.billing_run_eligible_sources WHERE billing_run_id=%s EXCEPT SELECT source_kind,"
        "source_id,source_period_start,source_period_end FROM app.billing_run_eligible_sources "
        "WHERE billing_run_id=%s) UNION ALL (SELECT source_kind,source_id,source_period_start,"
        "source_period_end FROM app.billing_run_eligible_sources WHERE billing_run_id=%s "
        "EXCEPT SELECT source_kind,source_id,source_period_start,source_period_end FROM "
        "app.billing_run_eligible_sources WHERE billing_run_id=%s))",
        (failed_run_id, successor_run_id, successor_run_id, failed_run_id),
    ).fetchone() == (True,)
    with pytest.raises(Error) as second_successor_is_rejected:
        with connection.transaction():
            insert_run(
                run_id=uuid4(),
                business_date=date(2054, 12, 25),
                period_start=date(2055, 1, 1),
                period_end=date(2055, 1, 31),
                system_actor_id=service_actor_id,
                logical_key="duplicate-failed-root-successor",
                started_at=failed_completed_at + timedelta(seconds=2),
                predecessor_run_id=failed_run_id,
            )
    assert second_successor_is_rejected.value.sqlstate == "23505"


def test_billing_run_completion_and_evidence_are_terminal_and_append_preserved(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id = setup_signed_lease(
        connection, start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
    )
    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )
    set_draft_correction_context(
        connection, actor_id=actor_id, reason="Correct Billing Run DRAFT evidence"
    )

    def record_missing_rent_sources(
        billing_run_id: UUID, billing_run_attempt_id: UUID, attempt_number: int
    ) -> None:
        missing_rows = connection.execute(
            "SELECT eligible.source_id,eligible.source_period_start,eligible.source_period_end "
            "FROM app.billing_run_eligible_sources AS eligible "
            "WHERE eligible.billing_run_id=%s AND NOT EXISTS ("
            "SELECT 1 FROM (SELECT item.outcome,item.invoice_id,item.recorded_at "
            "FROM app.billing_run_items AS item JOIN app.billing_run_attempts AS attempt "
            "ON attempt.id=item.billing_run_attempt_id "
            "WHERE item.billing_run_id=eligible.billing_run_id "
            "AND attempt.attempt_number<=%s AND item.source_kind='LEASE_PERIOD' "
            "AND item.source_id=eligible.source_id "
            "AND item.source_period_start=eligible.source_period_start "
            "AND item.source_period_end=eligible.source_period_end "
            "ORDER BY attempt.attempt_number DESC LIMIT 1) AS latest "
            "WHERE latest.outcome IN ('GENERATED','SKIPPED') AND EXISTS ("
            "SELECT 1 FROM app.invoices AS invoice WHERE invoice.id=latest.invoice_id "
            "AND invoice.status<>'VOID')) ",
            (billing_run_id, attempt_number),
        ).fetchall()
        for source_lease_id, source_period_start, source_period_end in missing_rows:
            assert isinstance(source_lease_id, UUID)
            assert isinstance(source_period_start, date)
            assert isinstance(source_period_end, date)
            active_invoice = connection.execute(
                "SELECT invoice.id,invoice.originating_billing_run_attempt_id "
                "FROM app.invoices AS invoice "
                "JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id "
                "WHERE invoice.status<>'VOID' AND line.category='RENT' "
                "AND line.source_lease_id=%s AND line.period_start=%s AND line.period_end=%s",
                (source_lease_id, source_period_start, source_period_end),
            ).fetchone()
            if active_invoice is None:
                customer_row = connection.execute(
                    "SELECT primary_tenant_id FROM app.leases WHERE id=%s",
                    (source_lease_id,),
                ).fetchone()
                assert customer_row is not None
                assert isinstance(customer_row[0], UUID)
                active_invoice_id, _ = create_recurring_rent_invoice(
                    connection,
                    actor_id=actor_id,
                    customer_id=customer_row[0],
                    lease_id=source_lease_id,
                    period_start=source_period_start,
                )
                outcome = "SKIPPED"
            else:
                assert isinstance(active_invoice[0], UUID)
                active_invoice_id = active_invoice[0]
                outcome = "GENERATED" if active_invoice[1] == billing_run_attempt_id else "SKIPPED"
            diagnostic_code = None if outcome == "GENERATED" else "ACTIVE_INVOICE_ALREADY_EXISTS"
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "diagnostic_code,recorded_at) VALUES "
                "(%s,%s,%s,'LEASE_PERIOD',%s,%s,%s,%s,%s,%s,"
                "GREATEST(statement_timestamp(),(SELECT started_at FROM "
                "app.billing_run_attempts WHERE id=%s)))",
                (
                    uuid4(),
                    billing_run_id,
                    billing_run_attempt_id,
                    source_lease_id,
                    source_period_start,
                    source_period_end,
                    outcome,
                    active_invoice_id,
                    diagnostic_code,
                    billing_run_attempt_id,
                ),
            )

    tenant_row = connection.execute(
        "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease_id,)
    ).fetchone()
    assert tenant_row is not None
    assert isinstance(tenant_row[0], UUID)
    preexisting_invoice_id, preexisting_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 8, 1),
        issue=False,
    )
    attachment_run_id = uuid4()
    attachment_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','preexisting-draft-attachment','2025-07-25','2025-08-01',"
        "'2025-08-31',%s,%s,'RUNNING',statement_timestamp()+interval '1 second')",
        (attachment_run_id, property_id, uuid4(), service_actor_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,statement_timestamp()+interval '2 seconds','RUNNING')",
        (attachment_attempt_id, attachment_run_id),
    )
    with pytest.raises(Error) as attach_preexisting_draft:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET originating_billing_run_attempt_id=%s,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (attachment_attempt_id, actor_id, preexisting_invoice_id),
            )
    assert attach_preexisting_draft.value.sqlstate == "55000"
    connection.execute(
        "DELETE FROM app.invoice_line_calculation_components WHERE invoice_line_id=%s",
        (preexisting_line_id,),
    )
    connection.execute("DELETE FROM app.invoice_lines WHERE id=%s", (preexisting_line_id,))
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',"
        "completed_at=statement_timestamp()+interval '3 seconds',"
        "diagnostic_code='preexisting-draft' WHERE id=%s",
        (attachment_attempt_id,),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='FAILED',"
        "completed_at=statement_timestamp()+interval '4 seconds',"
        "failure_code='preexisting-draft' WHERE id=%s",
        (attachment_run_id,),
    )
    provenance_run_id = uuid4()
    provenance_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','provenance-actor-binding','2025-08-25','2025-09-01',"
        "'2025-09-30',%s,%s,'RUNNING',statement_timestamp()-interval '2 seconds')",
        (provenance_run_id, property_id, uuid4(), service_actor_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,statement_timestamp()-interval '1 second','RUNNING')",
        (provenance_attempt_id, provenance_run_id),
    )
    post_start_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 9, 1),
        create_line=False,
        issue=False,
    )
    with pytest.raises(Error) as attach_post_start_draft:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET originating_billing_run_attempt_id=%s,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (provenance_attempt_id, actor_id, post_start_invoice_id),
            )
    assert attach_post_start_draft.value.sqlstate == "55000"
    other_actor_id = uuid4()
    connection.execute(
        "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
        "lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,'Other Billing Actor',"
        "'Other Billing Actor','active','optional','test')",
        (other_actor_id, f"billing-other-{other_actor_id}"),
    )
    mismatched_actor_invoice_id = uuid4()
    with pytest.raises(Error) as mismatched_creation_actor:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                "primary_category,status,invoice_date,due_date,billing_period_start,"
                "billing_period_end,rent_billing_kind,original_total_usd_cents,due_date_rule,"
                "due_date_source,created_by,updated_by,originating_billing_run_attempt_id) "
                "VALUES (%s,%s,%s,%s,'RENT','DRAFT','2025-09-01','2025-09-05',"
                "'2025-09-01','2025-09-30','RECURRING',80000,'RECURRING_RENT_FIFTH',"
                "'BR-RENT-018',%s,%s,%s)",
                (
                    mismatched_actor_invoice_id,
                    f"INV-{mismatched_actor_invoice_id.hex}",
                    tenant_row[0],
                    lease_id,
                    other_actor_id,
                    other_actor_id,
                    provenance_attempt_id,
                ),
            )
    assert mismatched_creation_actor.value.sqlstate == "55000"
    mismatched_update_invoice_id = uuid4()
    with pytest.raises(Error) as mismatched_initial_update_actor:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                "primary_category,status,invoice_date,due_date,billing_period_start,"
                "billing_period_end,rent_billing_kind,original_total_usd_cents,due_date_rule,"
                "due_date_source,created_by,updated_by,originating_billing_run_attempt_id) "
                "VALUES (%s,%s,%s,%s,'RENT','DRAFT','2025-09-01','2025-09-05',"
                "'2025-09-01','2025-09-30','RECURRING',80000,'RECURRING_RENT_FIFTH',"
                "'BR-RENT-018',%s,%s,%s)",
                (
                    mismatched_update_invoice_id,
                    f"INV-{mismatched_update_invoice_id.hex}",
                    tenant_row[0],
                    lease_id,
                    actor_id,
                    other_actor_id,
                    provenance_attempt_id,
                ),
            )
    assert mismatched_initial_update_actor.value.sqlstate == "55000"
    generated_draft_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 9, 1),
        create_line=False,
        issue=False,
        originating_billing_run_attempt_id=provenance_attempt_id,
    )
    with pytest.raises(Error) as mismatched_draft_update_actor:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET due_date_source='BR-RENT-018',version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (other_actor_id, generated_draft_id),
            )
    assert mismatched_draft_update_actor.value.sqlstate == "55000"
    immutable_generated_draft_id, immutable_generated_line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 9, 1),
        issue=False,
        originating_billing_run_attempt_id=provenance_attempt_id,
    )
    component_row = connection.execute(
        "SELECT id,created_by FROM app.invoice_line_calculation_components "
        "WHERE invoice_line_id=%s",
        (immutable_generated_line_id,),
    ).fetchone()
    assert component_row is not None
    assert component_row[1] == service_actor_id
    with pytest.raises(Error) as mismatched_generated_component_actor:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,"
                "component_sequence,component_kind,period_start,period_end,"
                "contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,"
                "calculation_trace,created_by) VALUES (%s,%s,2,'FULL_RECURRING_MONTH',"
                "'2025-09-01','2025-09-30',80000,30,30,80000,%s,%s)",
                (
                    uuid4(),
                    immutable_generated_line_id,
                    Jsonb({"formula": "mismatched_actor"}),
                    other_actor_id,
                ),
            )
    assert mismatched_generated_component_actor.value.sqlstate == "55000"
    with pytest.raises(Error) as mutate_generated_line:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_lines SET description='Changed generated line' WHERE id=%s",
                (immutable_generated_line_id,),
            )
    assert mutate_generated_line.value.sqlstate == "55000"
    with pytest.raises(Error) as mutate_generated_component:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoice_line_calculation_components SET amount_usd_cents=79999 "
                "WHERE id=%s",
                (component_row[0],),
            )
    assert mutate_generated_component.value.sqlstate == "55000"
    assert connection.execute(
        "SELECT status FROM app.invoices WHERE id=%s", (immutable_generated_draft_id,)
    ).fetchone() == ("DRAFT",)
    with pytest.raises(Error) as mismatched_issuance_actor:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (other_actor_id, other_actor_id, generated_draft_id),
            )
    assert mismatched_issuance_actor.value.sqlstate == "55000"
    with pytest.raises(Error) as mismatched_issuance_update_actor:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
                "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s "
                "WHERE id=%s",
                (actor_id, other_actor_id, generated_draft_id),
            )
    assert mismatched_issuance_update_actor.value.sqlstate == "55000"
    with pytest.raises(Error) as mismatched_generated_line_actor:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 9, 1),
                originating_billing_run_attempt_id=provenance_attempt_id,
                line_actor_id=other_actor_id,
            )
    assert mismatched_generated_line_actor.value.sqlstate == "55000"
    generated_abandoned_at = datetime.now(UTC)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=2,updated_at=%s,updated_by=%s WHERE id=%s",
        (generated_abandoned_at, service_actor_id, generated_draft_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Generated draft abandoned',%s,%s,"
        "'invoice.void')",
        (uuid4(), generated_draft_id, generated_abandoned_at, service_actor_id),
    )
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=2,updated_at=%s,updated_by=%s WHERE id=%s",
        (generated_abandoned_at, service_actor_id, immutable_generated_draft_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Immutable generated draft abandoned',%s,%s,"
        "'invoice.void')",
        (uuid4(), immutable_generated_draft_id, generated_abandoned_at, service_actor_id),
    )
    with pytest.raises(Error) as abandoned_generated_draft_cannot_succeed:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                "WHERE id=%s",
                (generated_abandoned_at + timedelta(microseconds=1), provenance_attempt_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert abandoned_generated_draft_cannot_succeed.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
        "diagnostic_code='generated-draft-abandoned' WHERE id=%s",
        (generated_abandoned_at + timedelta(microseconds=1), provenance_attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='FAILED',completed_at=%s,"
        "failure_code='generated-draft-abandoned' WHERE id=%s",
        (generated_abandoned_at + timedelta(microseconds=2), provenance_run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT invoice.status,attempt.outcome,run.status FROM app.invoices AS invoice "
        "JOIN app.billing_run_attempts AS attempt "
        "ON attempt.id=invoice.originating_billing_run_attempt_id "
        "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
        (generated_draft_id,),
    ).fetchone() == ("VOID", "FAILED", "FAILED")
    voided_generated_run_id = uuid4()
    skipped_before_generated_attempt_id = uuid4()
    voided_generated_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','generated-then-voided','2025-09-25','2025-10-01','2025-10-31',"
        "%s,%s,'RUNNING',statement_timestamp())",
        (voided_generated_run_id, property_id, uuid4(), service_actor_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,statement_timestamp(),'RUNNING')",
        (skipped_before_generated_attempt_id, voided_generated_run_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
        "source_kind,source_id,source_period_start,source_period_end,outcome,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-10-01','2025-10-31',"
        "'ERROR','transient-source-error',statement_timestamp())",
        (
            uuid4(),
            voided_generated_run_id,
            skipped_before_generated_attempt_id,
            lease_id,
        ),
    )
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',"
        "completed_at=statement_timestamp(),diagnostic_code='retry-after-skip' WHERE id=%s",
        (skipped_before_generated_attempt_id,),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,2,statement_timestamp(),'RUNNING')",
        (voided_generated_attempt_id, voided_generated_run_id),
    )
    voided_generated_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 10, 1),
        originating_billing_run_attempt_id=voided_generated_attempt_id,
    )
    voided_generated_at_row = connection.execute(
        "SELECT GREATEST(statement_timestamp(),max(recorded_at))"
        "+interval '1 microsecond' FROM app.billing_run_items "
        "WHERE billing_run_attempt_id=%s",
        (voided_generated_attempt_id,),
    ).fetchone()
    assert voided_generated_at_row is not None
    assert isinstance(voided_generated_at_row[0], datetime)
    voided_generated_at = voided_generated_at_row[0]
    with pytest.raises(Error) as void_cannot_predate_generated_item_evidence:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-10-01',"
                "'2025-10-31','GENERATED',%s,%s)",
                (
                    uuid4(),
                    voided_generated_run_id,
                    voided_generated_attempt_id,
                    lease_id,
                    voided_generated_invoice_id,
                    voided_generated_at + timedelta(microseconds=1),
                ),
            )
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (voided_generated_at, actor_id, voided_generated_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Backdated generated VOID',%s,%s,"
                "'invoice.void')",
                (uuid4(), voided_generated_invoice_id, voided_generated_at, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_cannot_predate_generated_item_evidence.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,recorded_at) VALUES "
        "(%s,%s,%s,'LEASE_PERIOD',%s,'2025-10-01','2025-10-31','GENERATED',%s,%s)",
        (
            uuid4(),
            voided_generated_run_id,
            voided_generated_attempt_id,
            lease_id,
            voided_generated_invoice_id,
            voided_generated_at - timedelta(microseconds=1),
        ),
    )
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (voided_generated_at, actor_id, voided_generated_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Generated Invoice corrected',%s,%s,"
        "'invoice.void')",
        (uuid4(), voided_generated_invoice_id, voided_generated_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as voided_generated_invoice_cannot_succeed:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                "WHERE id=%s",
                (
                    voided_generated_at + timedelta(microseconds=1),
                    voided_generated_attempt_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert voided_generated_invoice_cannot_succeed.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
        "diagnostic_code='generated-invoice-voided' WHERE id=%s",
        (
            voided_generated_at + timedelta(microseconds=1),
            voided_generated_attempt_id,
        ),
    )
    voided_retry_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,3,%s,'RUNNING')",
        (
            voided_retry_attempt_id,
            voided_generated_run_id,
            voided_generated_at + timedelta(microseconds=2),
        ),
    )
    with pytest.raises(Error) as empty_retry_cannot_reuse_voided_generation:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                "WHERE id=%s",
                (
                    voided_generated_at + timedelta(microseconds=3),
                    voided_retry_attempt_id,
                ),
            )
    assert empty_retry_cannot_reuse_voided_generation.value.sqlstate == "23514"
    record_missing_rent_sources(voided_generated_run_id, voided_retry_attempt_id, 3)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (voided_retry_attempt_id,),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (voided_generated_run_id,),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as half_open_period:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                "business_date,period_start,idempotency_key,system_actor_id,status,started_at) "
                "VALUES (%s,%s,'RENT','half-open-period','2025-02-25','2025-03-01',%s,%s,"
                "'RUNNING',now())",
                (uuid4(), property_id, uuid4(), service_actor_id),
            )
    assert half_open_period.value.sqlstate == "23514"
    with pytest.raises(Error) as utility_run_without_canonical_sources:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                "started_at) VALUES (%s,%s,'UTILITIES','utilities-source-deferred','2025-02-25',"
                "'2025-03-01','2025-03-31',%s,%s,'RUNNING',now())",
                (uuid4(), property_id, uuid4(), service_actor_id),
            )
    assert utility_run_without_canonical_sources.value.sqlstate == "23514"
    with pytest.raises(Error) as direct_terminal_run:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                "business_date,idempotency_key,system_actor_id,status,started_at,completed_at) "
                "VALUES (%s,%s,'RENT','direct-terminal','2025-02-25',%s,%s,'SUCCEEDED',"
                "now(),now())",
                (uuid4(), property_id, uuid4(), service_actor_id),
            )
    assert direct_terminal_run.value.sqlstate == "23514"
    run_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) "
        "VALUES (%s,%s,'RENT','rent-2025-03','2025-02-25','2025-03-01','2025-03-31',"
        "%s,%s,'RUNNING',now())",
        (run_id, property_id, uuid4(), service_actor_id),
    )
    attempt_id = uuid4()
    source_id = lease_id
    with pytest.raises(Error) as attempt_completed_before_start:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,"
                "started_at,completed_at,outcome) VALUES (%s,%s,1,now(),"
                "now()-interval '1 second','SUCCEEDED')",
                (uuid4(), run_id),
            )
    assert attempt_completed_before_start.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,now(),'RUNNING')",
        (attempt_id, run_id),
    )
    with pytest.raises(Error) as completion_before_item:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,recorded_at) "
                "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31','SKIPPED',"
                "now()+interval '1 hour')",
                (uuid4(), run_id, attempt_id, lease_id),
            )
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=now(),"
                "diagnostic_code='too-early' WHERE id=%s",
                (attempt_id,),
            )
    assert completion_before_item.value.sqlstate == "23514"
    with pytest.raises(Error) as overlapping_attempt:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,"
                "started_at,outcome) VALUES (%s,%s,3,now(),'RUNNING')",
                (uuid4(), run_id),
            )
    assert overlapping_attempt.value.sqlstate == "23514"
    with pytest.raises(Error) as wrong_source_kind:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,recorded_at) "
                "VALUES (%s,%s,%s,'UTILITY_PERIOD',%s,'2025-03-01','2025-03-31',"
                "'SKIPPED',now())",
                (uuid4(), run_id, attempt_id, uuid4()),
            )
    assert wrong_source_kind.value.sqlstate == "23514"
    with pytest.raises(Error) as nonexistent_lease_source:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,recorded_at) "
                "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31',"
                "'SKIPPED',now())",
                (uuid4(), run_id, attempt_id, uuid4()),
            )
    assert nonexistent_lease_source.value.sqlstate == "23514"
    with pytest.raises(Error) as source_period_outside_run:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,recorded_at) "
                "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-04-01','2025-04-30',"
                "'SKIPPED',now())",
                (uuid4(), run_id, attempt_id, lease_id),
            )
    assert source_period_outside_run.value.sqlstate == "55000"
    with pytest.raises(Error) as unrelated_generated_invoice:
        with connection.transaction():
            preexisting_invoice_id, _ = create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 3, 1),
            )
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01',"
                "'2025-03-31','GENERATED',%s,now())",
                (uuid4(), run_id, attempt_id, lease_id, preexisting_invoice_id),
            )
    assert unrelated_generated_invoice.value.sqlstate == "23514"
    with pytest.raises(Error) as running_attempt:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=now() WHERE id=%s",
                (run_id,),
            )
    assert running_attempt.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,diagnostic_code,recorded_at) "
        "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31','ERROR',"
        "'attempt-failed',now())",
        (uuid4(), run_id, attempt_id, source_id),
    )
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=now(),"
        "diagnostic_code='attempt-failed' WHERE id=%s",
        (attempt_id,),
    )
    successful_attempt_id = uuid4()
    with pytest.raises(Error) as retry_before_prior_completion:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,"
                "started_at,outcome) SELECT %s,%s,2,completed_at-interval '1 second','RUNNING' "
                "FROM app.billing_run_attempts WHERE id=%s",
                (uuid4(), run_id, attempt_id),
            )
    assert retry_before_prior_completion.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,2,now(),'RUNNING')",
        (successful_attempt_id, run_id),
    )
    with pytest.raises(Error) as detach_originating_draft:
        with connection.transaction():
            draft_origin_invoice_id, _ = create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 3, 1),
                issue=False,
                originating_billing_run_attempt_id=successful_attempt_id,
            )
            connection.execute(
                "UPDATE app.invoices SET originating_billing_run_attempt_id=NULL,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, draft_origin_invoice_id),
            )
    assert detach_originating_draft.value.sqlstate == "55000"
    with pytest.raises(Error) as complete_attempt_with_unattached_draft:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 3, 1),
                issue=False,
                originating_billing_run_attempt_id=successful_attempt_id,
            )
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
                "completed_at=statement_timestamp() WHERE id=%s",
                (successful_attempt_id,),
            )
    assert complete_attempt_with_unattached_draft.value.sqlstate == "23514"
    with pytest.raises(Error) as complete_attempt_with_unattached_invoice:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 3, 1),
                originating_billing_run_attempt_id=successful_attempt_id,
            )
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
                "completed_at=statement_timestamp() WHERE id=%s",
                (successful_attempt_id,),
            )
    assert complete_attempt_with_unattached_invoice.value.sqlstate == "23514"
    generated_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_row[0],
        lease_id=lease_id,
        period_start=date(2025, 3, 1),
        originating_billing_run_attempt_id=successful_attempt_id,
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,recorded_at) VALUES "
        "(%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31','GENERATED',%s,"
        "statement_timestamp())",
        (uuid4(), run_id, successful_attempt_id, source_id, generated_invoice_id),
    )
    second_unit_id = uuid4()
    second_tenant_id = uuid4()
    connection.execute(
        "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,created_by,"
        "updated_by) VALUES (%s,%s,%s,'2','ONE_BEDROOM','VACANT',%s,%s)",
        (
            second_unit_id,
            property_id,
            f"INVOICE-{second_unit_id.hex[:12]}",
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES "
        "(%s,'Second Billing Customer',%s,%s)",
        (second_tenant_id, actor_id, actor_id),
    )
    second_lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=second_unit_id,
        primary_tenant_id=second_tenant_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    sign_lease(connection, second_lease_id, actor_id)
    with pytest.raises(Error) as expand_sealed_eligible_source_snapshot:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_eligible_sources(billing_run_id,source_kind,"
                "source_id,source_period_start,source_period_end,snapshotted_at) VALUES "
                "(%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31',statement_timestamp())",
                (run_id, second_lease_id),
            )
    assert expand_sealed_eligible_source_snapshot.value.sqlstate == "55000"
    with pytest.raises(Error) as invoice_for_post_snapshot_lease:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=second_tenant_id,
                lease_id=second_lease_id,
                period_start=date(2025, 3, 1),
                originating_billing_run_attempt_id=successful_attempt_id,
            )
    assert invoice_for_post_snapshot_lease.value.sqlstate == "55000"
    with pytest.raises(Error) as item_for_post_snapshot_lease:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,recorded_at) "
                "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31','SKIPPED',"
                "statement_timestamp())",
                (uuid4(), run_id, successful_attempt_id, second_lease_id),
            )
    assert item_for_post_snapshot_lease.value.sqlstate == "23514"
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT app.billing_run_has_unresolved_sources(%s,2)", (run_id,)
    ).fetchone() == (False,)
    record_missing_rent_sources(run_id, successful_attempt_id, 2)
    assert connection.execute(
        "SELECT app.billing_run_has_missing_eligible_sources(%s,2)", (run_id,)
    ).fetchone() == (False,)
    assert connection.execute(
        "SELECT count(*) FROM app.billing_run_items WHERE billing_run_attempt_id=%s "
        "AND outcome IN ('CONFLICT','ERROR')",
        (successful_attempt_id,),
    ).fetchone() == (0,)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (successful_attempt_id,),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=statement_timestamp() "
        "WHERE id=%s",
        (run_id,),
    )
    assert connection.execute(
        "SELECT status,completed_at IS NOT NULL FROM app.billing_runs WHERE id=%s", (run_id,)
    ).fetchone() == ("SUCCEEDED", True)
    issued_and_completed = connection.execute(
        "SELECT invoice.issued_at,run.completed_at FROM app.invoices AS invoice "
        "JOIN app.billing_run_attempts AS attempt "
        "ON attempt.id=invoice.originating_billing_run_attempt_id "
        "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
        (generated_invoice_id,),
    ).fetchone()
    assert issued_and_completed is not None
    assert isinstance(issued_and_completed[0], datetime)
    assert isinstance(issued_and_completed[1], datetime)
    assert issued_and_completed[0] < issued_and_completed[1]
    backdated_generated_void_at = (
        issued_and_completed[0] + (issued_and_completed[1] - issued_and_completed[0]) / 2
    )
    with pytest.raises(Error) as generated_void_cannot_predate_successful_run:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (backdated_generated_void_at, actor_id, generated_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Backdated after run success',%s,%s,"
                "'invoice.void')",
                (
                    uuid4(),
                    generated_invoice_id,
                    backdated_generated_void_at,
                    actor_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert generated_void_cannot_predate_successful_run.value.sqlstate == "23514"
    valid_generated_void_at = issued_and_completed[1] + timedelta(microseconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (valid_generated_void_at, actor_id, generated_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Corrected after run success',%s,%s,"
        "'invoice.void')",
        (uuid4(), generated_invoice_id, valid_generated_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as overlap_with_terminal_run:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
                "started_at) VALUES (%s,%s,'RENT','overlap-terminal-history','2025-03-10',"
                "'2025-03-15','2025-04-15',%s,%s,'RUNNING',now())",
                (uuid4(), property_id, uuid4(), service_actor_id),
            )
    assert overlap_with_terminal_run.value.sqlstate == "23514"
    with pytest.raises(Error) as invoice_from_terminal_attempt:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=tenant_row[0],
                lease_id=lease_id,
                period_start=date(2025, 4, 1),
                issue=False,
                originating_billing_run_attempt_id=successful_attempt_id,
            )
    assert invoice_from_terminal_attempt.value.sqlstate == "55000"
    with pytest.raises(Error) as reopen:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_runs SET status='FAILED',failure_code='late-change' "
                "WHERE id=%s",
                (run_id,),
            )
    assert reopen.value.sqlstate == "55000"
    with pytest.raises(Error) as erase_attempt:
        with connection.transaction():
            connection.execute(
                "DELETE FROM app.billing_run_attempts WHERE billing_run_id=%s", (run_id,)
            )
    assert erase_attempt.value.sqlstate == "55000"
    with pytest.raises(Error) as append_attempt:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,"
                "started_at,completed_at,outcome) VALUES (%s,%s,3,now(),now(),'SUCCEEDED')",
                (uuid4(), run_id),
            )
    assert append_attempt.value.sqlstate == "55000"
    with pytest.raises(Error) as append_item:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,"
                "source_period_start,source_period_end,outcome,recorded_at) VALUES "
                "(%s,%s,%s,'LEASE_PERIOD',%s,'2025-03-01','2025-03-31','SKIPPED',now())",
                (uuid4(), run_id, successful_attempt_id, uuid4()),
            )
    assert append_item.value.sqlstate == "55000"

    latest_run_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','latest-attempt-wins','2025-04-25','2025-05-01','2025-05-31',"
        "%s,%s,'RUNNING',now())",
        (latest_run_id, property_id, uuid4(), service_actor_id),
    )
    successful_only_attempt_id = uuid4()
    with pytest.raises(Error) as terminal_attempt_insert:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
                "completed_at,outcome) VALUES (%s,%s,1,now(),now(),'SUCCEEDED')",
                (successful_only_attempt_id, latest_run_id),
            )
    assert terminal_attempt_insert.value.sqlstate == "23514"
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,now(),'RUNNING')",
        (successful_only_attempt_id, latest_run_id),
    )
    with pytest.raises(Error) as empty_attempt_success:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=now() "
                "WHERE id=%s",
                (successful_only_attempt_id,),
            )
    assert empty_attempt_success.value.sqlstate == "23514"
    record_missing_rent_sources(latest_run_id, successful_only_attempt_id, 1)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (successful_only_attempt_id,),
    )
    with pytest.raises(Error) as retry_after_success:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
                "completed_at,outcome,diagnostic_code) VALUES (%s,%s,2,now(),now(),'FAILED',"
                "'retry-after-success')",
                (uuid4(), latest_run_id),
            )
    assert retry_after_success.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (latest_run_id,),
    )

    error_run_id = uuid4()
    error_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','latest-error-item','2025-05-25','2025-06-01','2025-06-30',"
        "%s,%s,'RUNNING',now())",
        (error_run_id, property_id, uuid4(), service_actor_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,now(),'RUNNING')",
        (error_attempt_id, error_run_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,diagnostic_code,recorded_at) "
        "VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2025-06-01','2025-06-30','ERROR',"
        "'item-error',now())",
        (uuid4(), error_run_id, error_attempt_id, lease_id),
    )
    with pytest.raises(Error) as success_with_error:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=now() "
                "WHERE id=%s",
                (error_attempt_id,),
            )
    assert success_with_error.value.sqlstate == "23514"
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=now(),"
        "diagnostic_code='item-error' WHERE id=%s",
        (error_attempt_id,),
    )
    recovery_attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,2,now(),'RUNNING')",
        (recovery_attempt_id, error_run_id),
    )
    with pytest.raises(Error) as success_omitting_failed_source:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=now() "
                "WHERE id=%s",
                (recovery_attempt_id,),
            )
    assert success_omitting_failed_source.value.sqlstate == "23514"
    record_missing_rent_sources(error_run_id, recovery_attempt_id, 2)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (recovery_attempt_id,),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (error_run_id,),
    )
    assert connection.execute(
        "SELECT status FROM app.billing_runs WHERE id=%s", (error_run_id,)
    ).fetchone() == ("SUCCEEDED",)


def test_billing_run_retry_void_chronology_requires_post_void_resolution(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=customer_id,
        start_date=date(2023, 11, 1),
        end_date=date(2024, 12, 31),
    )
    sign_lease(connection, lease_id, actor_id)
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,'2023-11-01',%s,%s)",
        (uuid4(), lease_id, customer_id, actor_id, actor_id),
    )
    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )

    def start_run(*, logical_key: str, period_start: date, period_end: date) -> tuple[UUID, UUID]:
        run_id = uuid4()
        attempt_id = uuid4()
        connection.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
            "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
            "(%s,%s,'RENT',%s,%s,%s,%s,%s,%s,'RUNNING',statement_timestamp())",
            (
                run_id,
                property_id,
                logical_key,
                (period_start - timedelta(days=1)).replace(day=25),
                period_start,
                period_end,
                uuid4(),
                service_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,1,statement_timestamp(),'RUNNING')",
            (attempt_id, run_id),
        )
        return run_id, attempt_id

    def record_generated_invoice(
        *, run_id: UUID, attempt_id: UUID, period_start: date, period_end: date
    ) -> UUID:
        invoice_id, _ = create_recurring_rent_invoice(
            connection,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=period_start,
            originating_billing_run_attempt_id=attempt_id,
        )
        connection.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
            "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,%s,%s,'GENERATED',%s,"
            "statement_timestamp())",
            (
                uuid4(),
                run_id,
                attempt_id,
                lease_id,
                period_start,
                period_end,
                invoice_id,
            ),
        )
        return invoice_id

    def fail_attempt(attempt_id: UUID, diagnostic_code: str) -> None:
        connection.execute(
            "UPDATE app.billing_run_attempts SET outcome='FAILED',"
            "completed_at=statement_timestamp(),diagnostic_code=%s WHERE id=%s",
            (diagnostic_code, attempt_id),
        )

    def skip_other_eligible_sources(run_id: UUID, attempt_id: UUID) -> None:
        missing_sources = connection.execute(
            "SELECT eligible.source_id,eligible.source_period_start,eligible.source_period_end "
            "FROM app.billing_run_eligible_sources AS eligible WHERE eligible.billing_run_id=%s "
            "AND NOT EXISTS (SELECT 1 FROM app.billing_run_items AS item "
            "WHERE item.billing_run_attempt_id=%s AND item.source_kind=eligible.source_kind "
            "AND item.source_id=eligible.source_id "
            "AND item.source_period_start=eligible.source_period_start "
            "AND item.source_period_end=eligible.source_period_end)",
            (run_id, attempt_id),
        ).fetchall()
        for source_id, source_period_start, source_period_end in missing_sources:
            assert isinstance(source_id, UUID)
            assert isinstance(source_period_start, date)
            assert isinstance(source_period_end, date)
            active_invoice = connection.execute(
                "SELECT invoice.id FROM app.invoices AS invoice "
                "JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id "
                "WHERE invoice.status<>'VOID' AND line.category='RENT' "
                "AND line.source_lease_id=%s AND line.period_start=%s AND line.period_end=%s",
                (source_id, source_period_start, source_period_end),
            ).fetchone()
            if active_invoice is None:
                source_customer = connection.execute(
                    "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (source_id,)
                ).fetchone()
                assert source_customer is not None
                assert isinstance(source_customer[0], UUID)
                active_invoice_id, _ = create_recurring_rent_invoice(
                    connection,
                    actor_id=actor_id,
                    customer_id=source_customer[0],
                    lease_id=source_id,
                    period_start=source_period_start,
                )
            else:
                assert isinstance(active_invoice[0], UUID)
                active_invoice_id = active_invoice[0]
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "diagnostic_code,recorded_at) VALUES "
                "(%s,%s,%s,'LEASE_PERIOD',%s,%s,%s,'SKIPPED',%s,"
                "'ACTIVE_INVOICE_ALREADY_EXISTS',statement_timestamp())",
                (
                    uuid4(),
                    run_id,
                    attempt_id,
                    source_id,
                    source_period_start,
                    source_period_end,
                    active_invoice_id,
                ),
            )

    def start_retry(run_id: UUID, attempt_number: int, started_at: datetime | None = None) -> UUID:
        attempt_id = uuid4()
        connection.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,%s,COALESCE(%s,statement_timestamp()),'RUNNING')",
            (attempt_id, run_id, attempt_number, started_at),
        )
        return attempt_id

    successful_run_id, failed_origin_attempt_id = start_run(
        logical_key="failed-origin-later-success",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    successful_run_invoice_id = record_generated_invoice(
        run_id=successful_run_id,
        attempt_id=failed_origin_attempt_id,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    fail_attempt(failed_origin_attempt_id, "retry-after-generated")
    successful_retry_id = start_retry(successful_run_id, 2)
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2024-01-01','2024-01-31',"
        "'SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',statement_timestamp())",
        (
            uuid4(),
            successful_run_id,
            successful_retry_id,
            lease_id,
            successful_run_invoice_id,
        ),
    )
    skip_other_eligible_sources(successful_run_id, successful_retry_id)
    retry_completeness = connection.execute(
        "SELECT app.billing_run_has_unresolved_sources(%s,2),"
        "app.billing_run_has_missing_eligible_sources(%s,2)",
        (successful_run_id, successful_run_id),
    ).fetchone()
    retry_evidence = connection.execute(
        "SELECT eligible.source_id,eligible.source_period_start,eligible.source_period_end,"
        "attempt.attempt_number,item.outcome,item.invoice_id,"
        "(SELECT count(*) FROM app.invoice_void_events AS void_event "
        "WHERE void_event.invoice_id=item.invoice_id) "
        "FROM app.billing_run_eligible_sources AS eligible "
        "LEFT JOIN app.billing_run_items AS item "
        "ON item.billing_run_id=eligible.billing_run_id "
        "AND item.source_kind=eligible.source_kind AND item.source_id=eligible.source_id "
        "AND item.source_period_start=eligible.source_period_start "
        "AND item.source_period_end=eligible.source_period_end "
        "LEFT JOIN app.billing_run_attempts AS attempt ON attempt.id=item.billing_run_attempt_id "
        "WHERE eligible.billing_run_id=%s ORDER BY attempt.attempt_number",
        (successful_run_id,),
    ).fetchall()
    assert retry_completeness == (False, False), retry_evidence
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (successful_retry_id,),
    )
    preterminal_void_at_row = connection.execute(
        "SELECT max(recorded_at)+interval '1 microsecond' FROM app.billing_run_items "
        "WHERE billing_run_attempt_id=%s",
        (successful_retry_id,),
    ).fetchone()
    assert preterminal_void_at_row is not None
    assert isinstance(preterminal_void_at_row[0], datetime)
    preterminal_void_at = preterminal_void_at_row[0]
    with pytest.raises(Error) as successful_retry_dependency_cannot_be_voided_preterminal:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (preterminal_void_at, actor_id, successful_run_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Pre-terminal retry dependency',%s,%s,"
                "'invoice.void')",
                (
                    uuid4(),
                    successful_run_invoice_id,
                    preterminal_void_at,
                    actor_id,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert successful_retry_dependency_cannot_be_voided_preterminal.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT invoice.status,attempt.outcome,run.status FROM app.invoices AS invoice "
        "JOIN app.billing_run_attempts AS attempt ON attempt.id=%s "
        "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
        (successful_retry_id, successful_run_invoice_id),
    ).fetchone() == ("UNPAID", "SUCCEEDED", "RUNNING")
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=statement_timestamp() "
        "WHERE id=%s",
        (successful_run_id,),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    successful_run_completed_at_row = connection.execute(
        "SELECT completed_at FROM app.billing_runs WHERE id=%s", (successful_run_id,)
    ).fetchone()
    assert successful_run_completed_at_row is not None
    assert isinstance(successful_run_completed_at_row[0], datetime)
    successful_run_void_at = successful_run_completed_at_row[0] + timedelta(microseconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (successful_run_void_at, actor_id, successful_run_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Post-run correction',%s,%s,'invoice.void')",
        (uuid4(), successful_run_invoice_id, successful_run_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT invoice.status,attempt.outcome,run.status FROM app.invoices AS invoice "
        "JOIN app.billing_run_attempts AS attempt "
        "ON attempt.id=invoice.originating_billing_run_attempt_id "
        "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
        (successful_run_invoice_id,),
    ).fetchone() == ("VOID", "FAILED", "SUCCEEDED")

    future_skip_run_id, future_skip_attempt_id = start_run(
        logical_key="future-issued-skip-rejected",
        period_start=date(2024, 6, 1),
        period_end=date(2024, 6, 30),
    )
    future_skip_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=customer_id,
        lease_id=lease_id,
        period_start=date(2024, 6, 1),
        issue=False,
    )
    future_issued_at = datetime.now(UTC) + timedelta(days=1)
    connection.execute(
        "UPDATE app.invoices SET status='UNPAID',issued_at=%s,issued_by=%s,version=2,"
        "updated_at=%s,updated_by=%s WHERE id=%s",
        (
            future_issued_at,
            actor_id,
            future_issued_at,
            actor_id,
            future_skip_invoice_id,
        ),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as skipped_evidence_cannot_predate_invoice_issuance:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
                "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
                "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2024-06-01',"
                "'2024-06-30','SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',"
                "statement_timestamp())",
                (
                    uuid4(),
                    future_skip_run_id,
                    future_skip_attempt_id,
                    lease_id,
                    future_skip_invoice_id,
                ),
            )
    assert skipped_evidence_cannot_predate_invoice_issuance.value.sqlstate == "23514"

    stale_skip_run_id, stale_skip_origin_attempt_id = start_run(
        logical_key="stale-skip-before-void",
        period_start=date(2024, 2, 1),
        period_end=date(2024, 2, 29),
    )
    stale_skip_invoice_id = record_generated_invoice(
        run_id=stale_skip_run_id,
        attempt_id=stale_skip_origin_attempt_id,
        period_start=date(2024, 2, 1),
        period_end=date(2024, 2, 29),
    )
    fail_attempt(stale_skip_origin_attempt_id, "retry-before-void")
    stale_skip_retry_id = start_retry(stale_skip_run_id, 2)
    stale_skip_item_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2024-02-01','2024-02-29',"
        "'SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',statement_timestamp())",
        (
            stale_skip_item_id,
            stale_skip_run_id,
            stale_skip_retry_id,
            lease_id,
            stale_skip_invoice_id,
        ),
    )
    skip_other_eligible_sources(stale_skip_run_id, stale_skip_retry_id)
    stale_skip_recorded_at_row = connection.execute(
        "SELECT recorded_at FROM app.billing_run_items WHERE id=%s", (stale_skip_item_id,)
    ).fetchone()
    assert stale_skip_recorded_at_row is not None
    assert isinstance(stale_skip_recorded_at_row[0], datetime)
    stale_skip_void_at = stale_skip_recorded_at_row[0] + timedelta(microseconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (stale_skip_void_at, actor_id, stale_skip_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'VOID after stale skip',%s,%s,'invoice.void')",
        (uuid4(), stale_skip_invoice_id, stale_skip_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Error) as stale_skip_cannot_complete_after_void:
        with connection.transaction():
            connection.execute(
                "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                "WHERE id=%s",
                (stale_skip_void_at + timedelta(microseconds=1), stale_skip_retry_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert stale_skip_cannot_complete_after_void.value.sqlstate == "23514"
    failed_retry_completed_at_row = connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=(SELECT "
        "GREATEST(%s,max(recorded_at)+interval '1 microsecond') FROM app.billing_run_items "
        "WHERE billing_run_attempt_id=%s),diagnostic_code='stale-skip-before-void' "
        "WHERE id=%s RETURNING completed_at",
        (stale_skip_void_at + timedelta(microseconds=2), stale_skip_retry_id, stale_skip_retry_id),
    ).fetchone()
    assert failed_retry_completed_at_row is not None
    assert isinstance(failed_retry_completed_at_row[0], datetime)
    failed_retry_completed_at = failed_retry_completed_at_row[0]
    post_void_retry_id = start_retry(
        stale_skip_run_id, 3, failed_retry_completed_at + timedelta(microseconds=1)
    )
    replacement_invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=customer_id,
        lease_id=lease_id,
        period_start=date(2024, 2, 1),
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2024-02-01','2024-02-29',"
        "'SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',GREATEST(%s,(SELECT started_at "
        "FROM app.billing_run_attempts WHERE id=%s),(SELECT issued_at+interval '1 microsecond' "
        "FROM app.invoices WHERE id=%s)))",
        (
            uuid4(),
            stale_skip_run_id,
            post_void_retry_id,
            lease_id,
            replacement_invoice_id,
            stale_skip_void_at + timedelta(microseconds=4),
            post_void_retry_id,
            replacement_invoice_id,
        ),
    )
    skip_other_eligible_sources(stale_skip_run_id, post_void_retry_id)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=(SELECT "
        "GREATEST(%s,max(recorded_at)+interval '1 microsecond') FROM app.billing_run_items "
        "WHERE billing_run_attempt_id=%s) WHERE id=%s",
        (
            stale_skip_void_at + timedelta(microseconds=5),
            post_void_retry_id,
            post_void_retry_id,
        ),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=(SELECT "
        "completed_at+interval '1 microsecond' FROM app.billing_run_attempts WHERE id=%s) "
        "WHERE id=%s",
        (post_void_retry_id, stale_skip_run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status FROM app.billing_runs WHERE id=%s", (stale_skip_run_id,)
    ).fetchone() == ("SUCCEEDED",)

    pending_run_id, successful_pending_attempt_id = start_run(
        logical_key="successful-attempt-pending-run",
        period_start=date(2024, 3, 1),
        period_end=date(2024, 3, 31),
    )
    pending_run_invoice_id = record_generated_invoice(
        run_id=pending_run_id,
        attempt_id=successful_pending_attempt_id,
        period_start=date(2024, 3, 1),
        period_end=date(2024, 3, 31),
    )
    skip_other_eligible_sources(pending_run_id, successful_pending_attempt_id)
    pending_completeness = connection.execute(
        "SELECT app.billing_run_has_unresolved_sources(%s,1),"
        "app.billing_run_has_missing_eligible_sources(%s,1)",
        (pending_run_id, pending_run_id),
    ).fetchone()
    pending_evidence = connection.execute(
        "SELECT eligible.source_id,item.outcome,item.invoice_id,invoice.status "
        "FROM app.billing_run_eligible_sources AS eligible "
        "LEFT JOIN app.billing_run_items AS item ON item.billing_run_id=eligible.billing_run_id "
        "AND item.source_kind=eligible.source_kind AND item.source_id=eligible.source_id "
        "AND item.source_period_start=eligible.source_period_start "
        "AND item.source_period_end=eligible.source_period_end "
        "LEFT JOIN app.invoices AS invoice ON invoice.id=item.invoice_id "
        "WHERE eligible.billing_run_id=%s",
        (pending_run_id,),
    ).fetchall()
    assert pending_completeness == (False, False), pending_evidence
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',"
        "completed_at=statement_timestamp() WHERE id=%s",
        (successful_pending_attempt_id,),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    pending_attempt_completed_at_row = connection.execute(
        "SELECT completed_at FROM app.billing_run_attempts WHERE id=%s",
        (successful_pending_attempt_id,),
    ).fetchone()
    assert pending_attempt_completed_at_row is not None
    assert isinstance(pending_attempt_completed_at_row[0], datetime)
    premature_void_at = pending_attempt_completed_at_row[0] + timedelta(microseconds=1)
    with pytest.raises(Error) as successful_attempt_cannot_be_voided_before_run_completion:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (premature_void_at, actor_id, pending_run_invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Attempt terminal before run',%s,%s,"
                "'invoice.void')",
                (uuid4(), pending_run_invoice_id, premature_void_at, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert successful_attempt_cannot_be_voided_before_run_completion.value.sqlstate == "23514"
    pending_run_completed_at = premature_void_at + timedelta(microseconds=1)
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
        (pending_run_completed_at, pending_run_id),
    )
    valid_pending_run_void_at = pending_run_completed_at + timedelta(microseconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (valid_pending_run_void_at, actor_id, pending_run_invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Post-run correction',%s,%s,'invoice.void')",
        (uuid4(), pending_run_invoice_id, valid_pending_run_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT invoice.status,attempt.outcome,run.status FROM app.invoices AS invoice "
        "JOIN app.billing_run_attempts AS attempt "
        "ON attempt.id=invoice.originating_billing_run_attempt_id "
        "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
        (pending_run_invoice_id,),
    ).fetchone() == ("VOID", "SUCCEEDED", "SUCCEEDED")


def test_recurring_rent_and_billing_snapshot_follow_initial_and_termination_boundaries(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, tenant_id, lease_id = setup_signed_lease(
        connection,
        start_date=date(2198, 1, 1),
        end_date=date(2200, 12, 31),
        with_occupancy=False,
    )
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,'2198-01-21',%s,%s)",
        (uuid4(), lease_id, tenant_id, actor_id, actor_id),
    )
    for covered_period in (date(2198, 1, 1), date(2198, 2, 1)):
        with pytest.raises(Error) as recurring_before_initial_coverage_ends:
            with connection.transaction():
                create_recurring_rent_invoice(
                    connection,
                    actor_id=actor_id,
                    customer_id=tenant_id,
                    lease_id=lease_id,
                    period_start=covered_period,
                )
        assert recurring_before_initial_coverage_ends.value.sqlstate == "23514"

    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )

    def insert_run(
        run_id: UUID,
        *,
        business_date: date,
        period_start: date,
        period_end: date,
        logical_key: str,
        started_at: datetime,
        predecessor_run_id: UUID | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
            "business_date,period_start,period_end,idempotency_key,system_actor_id,status,"
            "started_at,predecessor_run_id) VALUES (%s,%s,'RENT',%s,%s,%s,%s,%s,%s,"
            "'RUNNING',%s,%s)",
            (
                run_id,
                property_id,
                logical_key,
                business_date,
                period_start,
                period_end,
                uuid4(),
                service_actor_id,
                started_at,
                predecessor_run_id,
            ),
        )

    initial_coverage_run_id = uuid4()
    insert_run(
        initial_coverage_run_id,
        business_date=date(2198, 1, 25),
        period_start=date(2198, 2, 1),
        period_end=date(2198, 2, 28),
        logical_key="initial-rent-coverage-is-not-recurring",
        started_at=datetime(2198, 1, 25, 5, tzinfo=UTC),
    )
    assert connection.execute(
        "SELECT count(*) FROM app.billing_run_eligible_sources "
        "WHERE billing_run_id=%s AND source_id=%s",
        (initial_coverage_run_id, lease_id),
    ).fetchone() == (0,)

    root_run_id = uuid4()
    root_attempt_id = uuid4()
    root_started_at = datetime(2198, 3, 25, 5, tzinfo=UTC)
    insert_run(
        root_run_id,
        business_date=date(2198, 3, 25),
        period_start=date(2198, 4, 1),
        period_end=date(2198, 4, 30),
        logical_key="billable-before-termination",
        started_at=root_started_at,
    )
    assert connection.execute(
        "SELECT source_id FROM app.billing_run_eligible_sources "
        "WHERE billing_run_id=%s AND source_id=%s",
        (root_run_id, lease_id),
    ).fetchall() == [(lease_id,)]
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (root_attempt_id, root_run_id, root_started_at),
    )
    root_completed_at = root_started_at + timedelta(seconds=1)
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
        "diagnostic_code='source-state-changed' WHERE id=%s",
        (root_completed_at, root_attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='FAILED',completed_at=%s,"
        "failure_code='source-state-changed' WHERE id=%s",
        (root_completed_at, root_run_id),
    )
    connection.execute(
        "UPDATE app.leases SET status='TERMINATED',"
        "terminated_at=TIMESTAMPTZ '2198-03-26 05:00:00+00',"
        "actual_termination_date='2198-03-31',termination_reason='Reviewed termination',"
        "version=version+1,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, lease_id),
    )
    successor_run_id = uuid4()
    successor_attempt_id = uuid4()
    successor_started_at = datetime(2198, 3, 26, 6, tzinfo=UTC)
    insert_run(
        successor_run_id,
        business_date=date(2198, 3, 25),
        period_start=date(2198, 4, 1),
        period_end=date(2198, 4, 30),
        logical_key="typed-ineligible-successor",
        started_at=successor_started_at,
        predecessor_run_id=root_run_id,
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (successor_attempt_id, successor_run_id, successor_started_at),
    )
    resolution_at = successor_started_at + timedelta(seconds=1)
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
        "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
        "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2198-04-01',"
        "'2198-04-30','SKIPPED',NULL,'SOURCE_NO_LONGER_ELIGIBLE',%s)",
        (
            uuid4(),
            successor_run_id,
            successor_attempt_id,
            lease_id,
            resolution_at,
        ),
    )
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s WHERE id=%s",
        (resolution_at + timedelta(microseconds=1), successor_attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
        (resolution_at + timedelta(microseconds=2), successor_run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT item.outcome,item.diagnostic_code,run.status "
        "FROM app.billing_run_items AS item JOIN app.billing_runs AS run "
        "ON run.id=item.billing_run_id WHERE item.billing_run_id=%s",
        (successor_run_id,),
    ).fetchone() == ("SKIPPED", "SOURCE_NO_LONGER_ELIGIBLE", "SUCCEEDED")


def test_billing_service_principal_revocation_is_repeatable_read_serialized(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _ = setup_signed_lease(
            setup, start_date=date(2079, 11, 1), end_date=date(2080, 12, 31)
        )
        service_actor_id = register_billing_service_principal(
            setup, property_id=property_id, created_by=actor_id
        )

    snapshot_ready = Event()
    disabled = Event()
    run_id = uuid4()

    def stale_snapshot_run() -> str:
        try:
            with psycopg.connect(migrated_database_url) as runner:
                runner.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                assert runner.execute(
                    "SELECT lifecycle_state FROM app.billing_service_principals WHERE actor_id=%s",
                    (service_actor_id,),
                ).fetchone() == ("active",)
                snapshot_ready.set()
                assert disabled.wait(timeout=10)
                runner.execute(
                    "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,"
                    "business_date,period_start,period_end,idempotency_key,system_actor_id,"
                    "status,started_at) VALUES (%s,%s,'RENT','stale-principal-snapshot',"
                    "'2079-12-25','2080-01-01','2080-01-31',%s,%s,'RUNNING',"
                    "TIMESTAMPTZ '2079-12-25 05:00:00+00')",
                    (run_id, property_id, uuid4(), service_actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def disable_principal() -> str:
        assert snapshot_ready.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as disabler:
                disabler.execute(
                    "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
                    "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
                    (actor_id, service_actor_id),
                )
            disabled.set()
            return "committed"
        except Error as error:
            disabled.set()
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        run_future = pool.submit(stale_snapshot_run)
        disable_future = pool.submit(disable_principal)
        assert disable_future.result(timeout=20) == "committed"
        assert run_future.result(timeout=20) == "40001"
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT lifecycle_state FROM app.billing_service_principals WHERE actor_id=%s",
            (service_actor_id,),
        ).fetchone() == ("disabled",)
        assert verify.execute(
            "SELECT count(*) FROM app.billing_runs WHERE id=%s", (run_id,)
        ).fetchone() == (0,)


def test_financial_event_actors_must_be_active_and_property_scoped(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_a, property_a, customer_a, lease_a = setup_signed_lease(connection)
    actor_b, _, customer_b, lease_b = setup_signed_lease(connection)
    service_a = register_billing_service_principal(
        connection, property_id=property_a, created_by=actor_a
    )
    with pytest.raises(Error) as unscoped_originless_service_invoice:
        with connection.transaction():
            invoice_id = uuid4()
            connection.execute(
                "INSERT INTO app.invoices(id,invoice_number,customer_id,primary_category,status,"
                "invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,"
                "created_by,updated_by) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','DRAFT',"
                "'2027-02-01','2027-02-01',0,'GOVERNING_SOURCE','originless-service',%s,%s)",
                (
                    invoice_id,
                    f"INV-{invoice_id.hex}",
                    customer_b,
                    service_a,
                    service_a,
                ),
            )
    assert unscoped_originless_service_invoice.value.sqlstate == "55000"

    with pytest.raises(Error) as scoped_originless_service_invoice:
        with connection.transaction():
            create_recurring_rent_invoice(
                connection,
                actor_id=service_a,
                customer_id=customer_a,
                lease_id=lease_a,
                issue=False,
            )
    assert scoped_originless_service_invoice.value.sqlstate == "55000"

    cross_property_invoice, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_a,
        customer_id=customer_a,
        lease_id=lease_a,
        issue=False,
    )
    with pytest.raises(Error) as cross_property_service_issuance:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET lease_id=%s,customer_id=%s,status='UNPAID',"
                "issued_at=statement_timestamp(),issued_by=%s,version=2,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (lease_b, customer_b, service_a, service_a, cross_property_invoice),
            )
    assert cross_property_service_issuance.value.sqlstate == "55000"

    invoice_b, line_b = create_recurring_rent_invoice(
        connection,
        actor_id=actor_b,
        customer_id=customer_b,
        lease_id=lease_b,
    )
    connection.execute(
        "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
        "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
        (actor_a, service_a),
    )
    with pytest.raises(Error) as disabled_service_void:
        with connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (service_a, invoice_b),
            )
    assert disabled_service_void.value.sqlstate == "55000"

    disabled_actor = uuid4()
    connection.execute(
        "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
        "lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,'Disabled finance actor',"
        "'Disabled finance actor','active','required','v1-039-regression')",
        (disabled_actor, f"disabled-finance-{disabled_actor}"),
    )
    connection.execute(
        "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
        (disabled_actor,),
    )
    with pytest.raises(Error) as disabled_actor_adjustment:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,%s,'CREDIT',1,'disabled-actor',"
                "'Disabled actor cannot mutate permanent evidence',statement_timestamp(),%s,"
                "'invoice.adjust')",
                (uuid4(), invoice_b, line_b, disabled_actor),
            )
    assert disabled_actor_adjustment.value.sqlstate == "55000"


def test_involuntary_midperiod_termination_has_terminal_billing_resolution(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id = setup_signed_lease(
        connection,
        start_date=date(2198, 1, 1),
        end_date=date(2200, 12, 31),
    )
    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )
    run_id = uuid4()
    attempt_id = uuid4()
    run_started_at = datetime(2198, 3, 25, 5, tzinfo=UTC)
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','midperiod-involuntary-resolution','2198-03-25','2198-04-01',"
        "'2198-04-30',%s,%s,'RUNNING',%s)",
        (run_id, property_id, uuid4(), service_actor_id, run_started_at),
    )
    assert connection.execute(
        "SELECT source_id FROM app.billing_run_eligible_sources WHERE billing_run_id=%s",
        (run_id,),
    ).fetchall() == [(lease_id,)]

    terminated_at = run_started_at + timedelta(days=1)
    connection.execute(
        "UPDATE app.leases SET status='TERMINATED',terminated_at=%s,"
        "actual_termination_date='2198-04-15',termination_reason='Involuntary termination',"
        "version=version+1,updated_at=%s,updated_by=%s WHERE id=%s",
        (terminated_at, terminated_at, actor_id, lease_id),
    )
    resolution_at = terminated_at + timedelta(seconds=2)
    assert connection.execute(
        "SELECT app.lease_is_billable_for_recurring_period(%s,'2198-04-01','2198-04-30',%s)",
        (lease_id, resolution_at),
    ).fetchone() == (False,)
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (attempt_id, run_id, terminated_at + timedelta(seconds=1)),
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2198-04-01','2198-04-30',"
        "'SKIPPED',NULL,'SOURCE_NO_LONGER_ELIGIBLE',%s)",
        (uuid4(), run_id, attempt_id, lease_id, resolution_at),
    )
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s WHERE id=%s",
        (resolution_at + timedelta(microseconds=1), attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
        (resolution_at + timedelta(microseconds=2), run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT item.outcome,item.diagnostic_code,run.status "
        "FROM app.billing_run_items AS item JOIN app.billing_runs AS run "
        "ON run.id=item.billing_run_id WHERE item.billing_run_id=%s",
        (run_id,),
    ).fetchone() == ("SKIPPED", "SOURCE_NO_LONGER_ELIGIBLE", "SUCCEEDED")


def test_external_skipped_invoice_void_must_follow_successful_run_completion(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, tenant_id, lease_id = setup_signed_lease(
        connection,
        start_date=date(2069, 1, 1),
        end_date=date(2070, 12, 31),
    )
    service_actor_id = register_billing_service_principal(
        connection, property_id=property_id, created_by=actor_id
    )
    invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=tenant_id,
        lease_id=lease_id,
        period_start=date(2070, 1, 1),
    )
    run_id = uuid4()
    attempt_id = uuid4()
    attempt_started_at = datetime(2069, 12, 25, 5, tzinfo=UTC)
    item_recorded_at = datetime(2070, 1, 1, 5, tzinfo=UTC)
    attempt_completed_at = datetime(2070, 1, 2, 5, tzinfo=UTC)
    run_completed_at = datetime(2070, 1, 3, 5, tzinfo=UTC)
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT','external-skip-void-chronology','2069-12-25','2070-01-01',"
        "'2070-01-31',%s,%s,'RUNNING',%s)",
        (run_id, property_id, uuid4(), service_actor_id, attempt_started_at),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
        "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
        (attempt_id, run_id, attempt_started_at),
    )
    connection.execute(
        "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,source_kind,"
        "source_id,source_period_start,source_period_end,outcome,invoice_id,diagnostic_code,"
        "recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2070-01-01','2070-01-31',"
        "'SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',%s)",
        (uuid4(), run_id, attempt_id, lease_id, invoice_id, item_recorded_at),
    )
    connection.execute(
        "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s WHERE id=%s",
        (attempt_completed_at, attempt_id),
    )
    connection.execute(
        "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
        (run_completed_at, run_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    invalid_void_at = attempt_completed_at + timedelta(hours=1)
    with pytest.raises(Error) as void_before_referencing_run_completion:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                "WHERE id=%s",
                (invalid_void_at, actor_id, invoice_id),
            )
            connection.execute(
                "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES (%s,%s,'Premature external skip VOID',%s,%s,"
                "'invoice.void')",
                (uuid4(), invoice_id, invalid_void_at, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert void_before_referencing_run_completion.value.sqlstate == "23514"

    valid_void_at = run_completed_at + timedelta(microseconds=1)
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s WHERE id=%s",
        (valid_void_at, actor_id, invoice_id),
    )
    connection.execute(
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Post-run external skip VOID',%s,%s,"
        "'invoice.void')",
        (uuid4(), invoice_id, valid_void_at, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT status FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone() == ("VOID",)


def test_external_skipped_invoice_void_and_success_are_serialized(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, tenant_id, lease_id = setup_signed_lease(
            setup,
            start_date=date(2196, 1, 1),
            end_date=date(2197, 12, 31),
        )
        service_actor_id = register_billing_service_principal(
            setup, property_id=property_id, created_by=actor_id
        )
        invoice_id, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=tenant_id,
            lease_id=lease_id,
            period_start=date(2197, 1, 1),
        )
        run_id = uuid4()
        attempt_id = uuid4()
        attempt_started_at = datetime(2196, 12, 25, 5, tzinfo=UTC)
        item_recorded_at = datetime(2197, 1, 1, 5, tzinfo=UTC)
        setup.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
            "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
            "(%s,%s,'RENT','external-skip-void-success-race','2196-12-25','2197-01-01',"
            "'2197-01-31',%s,%s,'RUNNING',%s)",
            (run_id, property_id, uuid4(), service_actor_id, attempt_started_at),
        )
        setup.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
            (attempt_id, run_id, attempt_started_at),
        )
        setup.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
            "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2197-01-01',"
            "'2197-01-31','SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',%s)",
            (uuid4(), run_id, attempt_id, lease_id, invoice_id, item_recorded_at),
        )

    race_barrier = Barrier(2)
    attempt_completed_at = datetime(2197, 1, 2, 5, tzinfo=UTC)
    run_completed_at = datetime(2197, 1, 3, 5, tzinfo=UTC)
    void_at = attempt_completed_at + timedelta(hours=1)

    def complete_run() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                race_barrier.wait()
                worker.execute(
                    "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                    "WHERE id=%s",
                    (attempt_completed_at, attempt_id),
                )
                worker.execute(
                    "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
                    (run_completed_at, run_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def void_invoice() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                race_barrier.wait()
                worker.execute("SET CONSTRAINTS ALL DEFERRED")
                worker.execute(
                    "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                    "WHERE id=%s",
                    (void_at, actor_id, invoice_id),
                )
                worker.execute(
                    "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,"
                    "'Concurrent external skip correction',%s,%s,'invoice.void')",
                    (uuid4(), invoice_id, void_at, actor_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion_future = pool.submit(complete_run)
        void_future = pool.submit(void_invoice)
        results = [completion_future.result(timeout=20), void_future.result(timeout=20)]
    assert sorted(results) == ["23514", "committed"]

    with psycopg.connect(migrated_database_url) as verify:
        state = verify.execute(
            "SELECT invoice.status,void_event.occurred_at,attempt.outcome,attempt.completed_at,"
            "run.status,run.completed_at FROM app.invoices AS invoice "
            "LEFT JOIN app.invoice_void_events AS void_event ON void_event.invoice_id=invoice.id "
            "JOIN app.billing_run_items AS item ON item.invoice_id=invoice.id "
            "JOIN app.billing_run_attempts AS attempt ON attempt.id=item.billing_run_attempt_id "
            "JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id WHERE invoice.id=%s",
            (invoice_id,),
        ).fetchone()
    assert state is not None
    if state[0] == "VOID":
        assert state[1] == void_at
        assert state[2:] == ("RUNNING", None, "RUNNING", None)
    else:
        assert state == (
            "UNPAID",
            None,
            "SUCCEEDED",
            attempt_completed_at,
            "SUCCEEDED",
            run_completed_at,
        )


def test_cumulative_retry_invoice_void_and_success_are_serialized(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, tenant_a, lease_a = setup_signed_lease(
            setup,
            start_date=date(2194, 1, 1),
            end_date=date(2195, 12, 31),
        )
        _, second_property_id, tenant_b, lease_b = setup_signed_lease(
            setup,
            start_date=date(2194, 1, 1),
            end_date=date(2195, 12, 31),
        )
        assert second_property_id == property_id
        service_actor_id = register_billing_service_principal(
            setup, property_id=property_id, created_by=actor_id
        )
        invoice_a, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=tenant_a,
            lease_id=lease_a,
            period_start=date(2195, 1, 1),
        )
        invoice_b, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor_id,
            customer_id=tenant_b,
            lease_id=lease_b,
            period_start=date(2195, 1, 1),
        )
        run_id = uuid4()
        first_attempt_id = uuid4()
        retry_attempt_id = uuid4()
        run_started_at = datetime(2194, 12, 25, 5, tzinfo=UTC)
        setup.execute(
            "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
            "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
            "(%s,%s,'RENT','cumulative-external-skip-void-race','2194-12-25','2195-01-01',"
            "'2195-01-31',%s,%s,'RUNNING',%s)",
            (run_id, property_id, uuid4(), service_actor_id, run_started_at),
        )
        assert setup.execute(
            "SELECT count(*) FROM app.billing_run_eligible_sources WHERE billing_run_id=%s",
            (run_id,),
        ).fetchone() == (2,)
        setup.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,1,%s,'RUNNING')",
            (first_attempt_id, run_id, run_started_at),
        )
        first_item_at = datetime(2195, 1, 1, 5, tzinfo=UTC)
        setup.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
            "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2195-01-01',"
            "'2195-01-31','SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',%s)",
            (uuid4(), run_id, first_attempt_id, lease_a, invoice_a, first_item_at),
        )
        setup.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,"
            "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2195-01-01',"
            "'2195-01-31','ERROR','transient-source-error',%s)",
            (uuid4(), run_id, first_attempt_id, lease_b, first_item_at),
        )
        first_completed_at = first_item_at + timedelta(days=1)
        setup.execute(
            "UPDATE app.billing_run_attempts SET outcome='FAILED',completed_at=%s,"
            "diagnostic_code='transient-source-error' WHERE id=%s",
            (first_completed_at, first_attempt_id),
        )
        retry_started_at = first_completed_at + timedelta(microseconds=1)
        setup.execute(
            "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,"
            "outcome) VALUES (%s,%s,2,%s,'RUNNING')",
            (retry_attempt_id, run_id, retry_started_at),
        )
        retry_item_at = first_completed_at + timedelta(days=1)
        setup.execute(
            "INSERT INTO app.billing_run_items(id,billing_run_id,billing_run_attempt_id,"
            "source_kind,source_id,source_period_start,source_period_end,outcome,invoice_id,"
            "diagnostic_code,recorded_at) VALUES (%s,%s,%s,'LEASE_PERIOD',%s,'2195-01-01',"
            "'2195-01-31','SKIPPED',%s,'ACTIVE_INVOICE_ALREADY_EXISTS',%s)",
            (uuid4(), run_id, retry_attempt_id, lease_b, invoice_b, retry_item_at),
        )

    race_barrier = Barrier(2)
    retry_completed_at = retry_item_at + timedelta(days=1)
    run_completed_at = retry_completed_at + timedelta(days=1)
    void_at = retry_completed_at + timedelta(hours=1)

    def complete_retry() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                race_barrier.wait()
                worker.execute(
                    "UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=%s "
                    "WHERE id=%s",
                    (retry_completed_at, retry_attempt_id),
                )
                worker.execute(
                    "UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=%s WHERE id=%s",
                    (run_completed_at, run_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def void_prior_attempt_invoice() -> str:
        try:
            with psycopg.connect(migrated_database_url) as worker:
                race_barrier.wait()
                worker.execute("SET CONSTRAINTS ALL DEFERRED")
                worker.execute(
                    "UPDATE app.invoices SET status='VOID',version=3,updated_at=%s,updated_by=%s "
                    "WHERE id=%s",
                    (void_at, actor_id, invoice_a),
                )
                worker.execute(
                    "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,"
                    "'Concurrent cumulative retry correction',%s,%s,'invoice.void')",
                    (uuid4(), invoice_a, void_at, actor_id),
                )
                worker.execute("SET CONSTRAINTS ALL IMMEDIATE")
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion_future = pool.submit(complete_retry)
        void_future = pool.submit(void_prior_attempt_invoice)
        results = [completion_future.result(timeout=20), void_future.result(timeout=20)]
    assert sorted(results) == ["23514", "committed"]

    with psycopg.connect(migrated_database_url) as verify:
        state = verify.execute(
            "SELECT invoice.status,void_event.occurred_at,attempt.outcome,attempt.completed_at,"
            "run.status,run.completed_at FROM app.invoices AS invoice "
            "LEFT JOIN app.invoice_void_events AS void_event ON void_event.invoice_id=invoice.id "
            "JOIN app.billing_runs AS run ON run.id=%s "
            "JOIN app.billing_run_attempts AS attempt ON attempt.id=%s WHERE invoice.id=%s",
            (run_id, retry_attempt_id, invoice_a),
        ).fetchone()
    assert state is not None
    if state[0] == "VOID":
        assert state[1] == void_at
        assert state[2:] == ("RUNNING", None, "RUNNING", None)
    else:
        assert state == (
            "UNPAID",
            None,
            "SUCCEEDED",
            retry_completed_at,
            "SUCCEEDED",
            run_completed_at,
        )


def test_lease_and_occupancy_writers_share_one_advisory_lock_order(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        lease_id = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2088, 1, 1),
            end_date=date(2089, 12, 31),
        )
        sign_lease(setup, lease_id, actor_id)
        setup.execute(
            "CREATE TABLE app.v1_039_lock_order_probe("
            "event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "probe text NOT NULL,guard_key text NOT NULL)"
        )
        setup.execute(
            "CREATE FUNCTION app.capture_v1_039_lock_order_probe() RETURNS trigger "
            "LANGUAGE plpgsql SET search_path=pg_catalog AS $$ "
            "DECLARE v_probe text; BEGIN "
            "v_probe:=NULLIF(current_setting('app.v1_039_lock_probe',true),''); "
            "IF v_probe IS NOT NULL THEN "
            "INSERT INTO app.v1_039_lock_order_probe(probe,guard_key) "
            "VALUES (v_probe,NEW.guard_key); END IF; RETURN NEW; END $$"
        )
        setup.execute(
            "CREATE TRIGGER invoice_guards_v1_039_order_probe AFTER INSERT OR UPDATE "
            "ON app.invoice_serialization_guards FOR EACH ROW "
            "EXECUTE FUNCTION app.capture_v1_039_lock_order_probe()"
        )

    start_together = Barrier(2)

    def update_lease() -> str:
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute("SELECT set_config('app.v1_039_lock_probe','lease',true)")
                writer.execute("SET LOCAL lock_timeout='10s'")
                start_together.wait(timeout=10)
                writer.execute(
                    "UPDATE app.leases SET version=version+1,updated_at=statement_timestamp(),"
                    "updated_by=%s WHERE id=%s",
                    (actor_id, lease_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    def insert_occupancy() -> str:
        try:
            with psycopg.connect(migrated_database_url) as writer:
                writer.execute("SELECT set_config('app.v1_039_lock_probe','occupancy',true)")
                writer.execute("SET LOCAL lock_timeout='10s'")
                start_together.wait(timeout=10)
                writer.execute(
                    "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                    "created_by,updated_by) VALUES (%s,%s,%s,'2088-01-01',%s,%s)",
                    (uuid4(), lease_id, tenant_id, actor_id, actor_id),
                )
            return "committed"
        except Error as error:
            return error.sqlstate or "error"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            lease_future = pool.submit(update_lease)
            occupancy_future = pool.submit(insert_occupancy)
            assert sorted(
                [lease_future.result(timeout=20), occupancy_future.result(timeout=20)]
            ) == ["committed", "committed"]
        with psycopg.connect(migrated_database_url) as verify:
            rows = verify.execute(
                "SELECT probe,array_agg(guard_key ORDER BY event_id) "
                "FROM app.v1_039_lock_order_probe GROUP BY probe ORDER BY probe"
            ).fetchall()
        expected_order = [
            f"invoice-property-service:{property_id}",
            f"billing-run-eligibility:{property_id}",
            f"invoice-lease:{lease_id}",
        ]
        assert rows == [("lease", expected_order), ("occupancy", expected_order)]
    finally:
        with psycopg.connect(migrated_database_url) as cleanup:
            cleanup.execute(
                "DROP TRIGGER IF EXISTS invoice_guards_v1_039_order_probe "
                "ON app.invoice_serialization_guards"
            )
            cleanup.execute("DROP FUNCTION IF EXISTS app.capture_v1_039_lock_order_probe()")
            cleanup.execute("DROP TABLE IF EXISTS app.v1_039_lock_order_probe")
