"""Unit cleaning rate and the move-out Unit cleaning charge (BR-UNIT-014, BR-MOVEOUT-013)."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CreateInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceInvalidError,
    InvoiceNotFoundError,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    RecordOneTimeChargeCommand,
    RecordUnitCleaningChargeCommand,
    SetUnitCleaningRateCommand,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import setup_historical_move_in
from test_physical_move_out_migration import record as record_move_out
from test_physical_move_out_migration import source as move_out_source

ALL_CAPABILITIES = (
    "invoices.read",
    "invoices.create",
    "invoices.issue",
    "invoices.adjust",
    "property.manage",
)
ONE_TIME_RULE = "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS"


def staff(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in capabilities or ALL_CAPABILITIES
        ),
    )


def invoices() -> PostgresInvoiceService:
    return PostgresInvoiceService(runtime_database_url(), financial_database_url())


def scalar(url: str, query: str, parameters: tuple[object, ...] = ()) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row[0]


def unit_of(url: str, lease: UUID) -> UUID:
    return UUID(str(scalar(url, "SELECT unit_id FROM app.leases WHERE id=%s", (lease,))))


def moved_out_lease(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    """Return human, Property, Lease and Unit for a Lease with a recorded physical move-out."""
    human, prop, lease, request = move_out_source(url)
    record_move_out(prop, lease, human, request)
    return human, prop, lease, unit_of(url, lease)


def second_unit(url: str, human: UUID, prop: UUID) -> UUID:
    """V1 has exactly one Property per database, so a second Unit shares that Property."""
    unit = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.units (id,property_id,unit_number,floor,unit_type,status,"
            "created_by,updated_by) VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
            (unit, prop, f"CLN-{unit.hex[:12]}", human, human),
        )
    return unit


def issue_day_of(url: str, invoice: object) -> Any:
    return scalar(
        url,
        "SELECT timezone('Asia/Phnom_Penh',issued_at)::date FROM app.invoices WHERE id=%s",
        (UUID(str(invoice)),),
    )


def set_rate(
    prop: UUID, unit: UUID, who: AuthenticatedActor, cents: int, current: UUID | None = None
) -> dict[str, object]:
    return invoices().set_unit_cleaning_rate(
        prop,
        SetUnitCleaningRateCommand(uuid4(), unit, current, cents, "Configured cleaning rate"),
        actor=who,
    )


def raw_charge(url: str, prop: UUID, human: UUID, lease: UUID, rate: UUID) -> object:
    with psycopg.connect(financial_database_url()) as connection:
        row = connection.execute(
            "SELECT app.record_unit_cleaning_charge(%s,%s,%s,%s,%s)",
            (prop, human, uuid4(), lease, rate),
        ).fetchone()
    assert row is not None
    return row[0]


def cleaning_rows(url: str, lease: UUID) -> tuple[int, int]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT (SELECT count(*) FROM app.unit_cleaning_charges WHERE lease_id=%s),"
            "(SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE lease_id=%s)",
            (lease, lease),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def issue(
    prop: UUID, obligation: UUID, who: AuthenticatedActor, command: IssueInvoiceCommand | None
) -> dict[str, object]:
    service = invoices()
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=who)
    version = cast(int, draft["version"])
    request = replace(command, expected_version=version) if command else None
    return service.issue(
        prop, UUID(str(draft["id"])), request or IssueInvoiceCommand(uuid4(), version), actor=who
    )


def test_cleaning_charge_uses_the_current_rate_once_per_lease_and_is_due_issue_plus_days(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, unit = moved_out_lease(url)
    who = staff(human, prop)
    first = set_rate(prop, unit, who, 2_500)
    assert invoices().unit_cleaning_rate(prop, unit, actor=who) == first
    command = RecordUnitCleaningChargeCommand(uuid4(), lease, UUID(str(first["id"])))
    recorded = invoices().record_unit_cleaning_charge(prop, command, actor=who)
    primary = scalar(url, "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease,))
    assert recorded["amount_usd_cents"] == 2_500
    assert recorded["rate_usd_cents"] == 2_500
    assert recorded["category"] == "MISCELLANEOUS_CHARGES"
    assert recorded["description"] == "Unit cleaning charge"
    assert recorded["customer_id"] == str(primary)
    assert recorded["lease_id"] == str(lease)
    assert recorded["unit_id"] == str(unit)
    assert recorded["cleaning_rate_id"] == first["id"]
    assert recorded["due_date_rule"] == ONE_TIME_RULE
    assert recorded["authorization_reference"] == "invoices.create"
    assert invoices().record_unit_cleaning_charge(prop, command, actor=who) == recorded
    with pytest.raises(InvoiceConflictError):
        invoices().record_unit_cleaning_charge(prop, replace(command, charge_id=uuid4()), actor=who)
    with pytest.raises(InvoiceConflictError):
        invoices().record_unit_cleaning_charge(
            prop, replace(command, expected_rate_id=uuid4()), actor=who
        )
    second = set_rate(prop, unit, who, 4_000, UUID(str(first["id"])))
    assert second["supersedes_rate_id"] == first["id"]
    assert invoices().record_unit_cleaning_charge(prop, command, actor=who) == recorded
    other = RecordOneTimeChargeCommand(
        uuid4(), "MISCELLANEOUS_CHARGES", primary, None, None, "Key card", 500, "Lost", "Log 1"
    )
    invoices().record_one_time_charge(prop, other, actor=who)
    # The identity check runs before the one-per-Lease check (P4503), so 23505 proves it.
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation, match="identity was reused"):
            connection.execute(
                "SELECT app.record_unit_cleaning_charge(%s,%s,%s,%s,%s)",
                (prop, human, other.charge_id, lease, UUID(str(second["id"]))),
            )
    issued = issue(prop, command.charge_id, who, None)
    issue_day = issue_day_of(url, issued["id"])
    days = scalar(url, "SELECT one_time_charge_due_days FROM app.properties WHERE id=%s", (prop,))
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT i.due_date,i.due_date_rule,i.due_date_source,l.amount_usd_cents "
            "FROM app.invoices i JOIN app.invoice_lines l ON l.invoice_id=i.id WHERE i.id=%s",
            (UUID(str(issued["id"])),),
        ).fetchall() == [
            (issue_day + timedelta(days=int(days)), ONE_TIME_RULE, "BR-INV-018", 2_500)
        ]
        assert connection.execute(
            "SELECT action,count(*) FROM app.audit_events WHERE property_id=%s "
            "AND entity_id IN (%s,%s,%s) GROUP BY action ORDER BY 1",
            (prop, UUID(str(first["id"])), UUID(str(second["id"])), command.charge_id),
        ).fetchall() == [("invoice.one_time_charge.recorded", 1), ("unit.cleaning_rate.set", 2)]
        assert connection.execute(
            "SELECT reason,evidence_reference FROM app.authorized_nonrecurring_obligations "
            "WHERE id=%s",
            (command.charge_id,),
        ).fetchone() == (
            "Unit cleaning charge at move-out (BR-MOVEOUT-013)",
            f"unit-cleaning-rate:{first['id']}",
        )
    for table in ("unit_cleaning_rates", "unit_cleaning_charges"):
        for statement in (
            f"UPDATE app.{table} SET recorded_at=recorded_at",
            f"DELETE FROM app.{table}",
            # The rates table is referenced by the charges table, so truncate both together.
            "TRUNCATE app.unit_cleaning_rates, app.unit_cleaning_charges"
            if table == "unit_cleaning_rates"
            else f"TRUNCATE app.{table}",
        ):
            with psycopg.connect(url) as connection:
                with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                    connection.execute(statement)


def test_cleaning_charge_due_date_override_and_reduction_by_credit_adjustment(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, unit = moved_out_lease(url)
    who = staff(human, prop)
    rate = set_rate(prop, unit, who, 3_000)
    command = RecordUnitCleaningChargeCommand(uuid4(), lease, UUID(str(rate["id"])))
    invoices().record_unit_cleaning_charge(prop, command, actor=who)
    # The business date before issue; the override must not precede the issue date.
    due = scalar(url, "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date") + timedelta(
        days=20
    )
    issued = issue(
        prop,
        command.charge_id,
        who,
        IssueInvoiceCommand(uuid4(), 1, due, "Customer asked for the end of the month"),
    )
    invoice = UUID(str(issued["id"]))
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT i.due_date,i.due_date_override_reason,i.due_date_set_by,i.version,l.id "
            "FROM app.invoices i JOIN app.invoice_lines l ON l.invoice_id=i.id WHERE i.id=%s",
            (invoice,),
        ).fetchone()
    assert row is not None
    assert row[:3] == (due, "Customer asked for the end of the month", human)
    reduction = AdjustInvoiceCommand(
        uuid4(),
        UUID(str(row[4])),
        AdjustmentType.CREDIT,
        1_000,
        "cleaning-reduction/approved",
        "Unit was left mostly clean",
        int(row[3]),
    )
    with pytest.raises(InvoiceAuthorizationError):
        invoices().adjust(
            prop,
            invoice,
            reduction,
            actor=staff(human, prop, "invoices.read", "invoices.create", "invoices.issue"),
        )
    with pytest.raises(ValueError, match="reason"):
        replace(reduction, reason=" ")
    invoices().adjust(prop, invoice, reduction, actor=who)
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT adjustment_type,amount_usd_cents,reason FROM app.invoice_adjustments "
            "WHERE invoice_id=%s",
            (invoice,),
        ).fetchall() == [("CREDIT", 1_000, "Unit was left mostly clean")]
        assert connection.execute(
            "SELECT o.authorized_amount_usd_cents,c.rate_usd_cents,l.amount_usd_cents "
            "FROM app.authorized_nonrecurring_obligations o "
            "JOIN app.unit_cleaning_charges c ON c.obligation_id=o.id "
            "JOIN app.invoice_lines l ON l.authorized_obligation_id=o.id WHERE o.id=%s",
            (command.charge_id,),
        ).fetchone() == (3_000, 3_000, 3_000)


def test_cleaning_charge_is_refused_without_move_in_move_out_rate_or_a_positive_rate(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    move_flow, mover, move = setup_historical_move_in(
        url, signed_day_offset=-1, receipt_day_offset=-1
    )
    human, prop, never = move_flow.actor_id, move_flow.property_id, move.lease_id
    who = staff(human, prop)
    rate = set_rate(prop, unit_of(url, never), who, 2_000)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="never moved in"):
        raw_charge(url, prop, human, never, UUID(str(rate["id"])))
    with pytest.raises(InvoiceInvalidError):
        invoices().record_unit_cleaning_charge(
            prop, RecordUnitCleaningChargeCommand(uuid4(), never, UUID(str(rate["id"]))), actor=who
        )
    assert cleaning_rows(url, never) == (0, 0)

    move_flow.complete(move, actor=mover)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="recorded move-out"):
        raw_charge(url, prop, human, never, UUID(str(rate["id"])))
    assert cleaning_rows(url, never) == (0, 0)

    human, prop, lease, unit = moved_out_lease(url)
    who = staff(human, prop)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="no cleaning rate"):
        raw_charge(url, prop, human, lease, uuid4())
    zero = set_rate(prop, unit, who, 0)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="rate is zero"):
        raw_charge(url, prop, human, lease, UUID(str(zero["id"])))
    positive = set_rate(prop, unit, who, 1_800, UUID(str(zero["id"])))
    with pytest.raises(psycopg.Error) as stale:
        raw_charge(url, prop, human, lease, UUID(str(zero["id"])))
    assert stale.value.sqlstate == "P4503"
    with pytest.raises(psycopg.errors.NoDataFound, match="Lease was not found"):
        raw_charge(url, prop, human, uuid4(), UUID(str(positive["id"])))
    elsewhere = uuid4()
    with pytest.raises(InvoiceNotFoundError):
        invoices().record_unit_cleaning_charge(
            elsewhere,
            RecordUnitCleaningChargeCommand(uuid4(), lease, UUID(str(positive["id"]))),
            actor=staff(human, elsewhere, "invoices.create"),
        )
    assert cleaning_rows(url, lease) == (0, 0)


def test_cleaning_rate_chain_is_linear_scoped_replay_safe_and_authorized(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, _, unit = moved_out_lease(url)
    manager = staff(human, prop, "property.manage")
    assert invoices().unit_cleaning_rate(prop, unit, actor=manager) is None
    command = SetUnitCleaningRateCommand(uuid4(), unit, None, 2_200, "First rate")
    first = invoices().set_unit_cleaning_rate(prop, command, actor=manager)
    assert invoices().set_unit_cleaning_rate(prop, command, actor=manager) == first
    with pytest.raises(InvoiceConflictError):
        invoices().set_unit_cleaning_rate(
            prop, replace(command, rate_usd_cents=2_300), actor=manager
        )
    with pytest.raises(InvoiceConflictError):
        invoices().set_unit_cleaning_rate(prop, replace(command, rate_id=uuid4()), actor=manager)
    with pytest.raises(InvoiceAuthorizationError):
        invoices().set_unit_cleaning_rate(
            prop, replace(command, rate_id=uuid4()), actor=staff(human, prop, "invoices.create")
        )
    stray = uuid4()
    with pytest.raises(InvoiceNotFoundError):
        invoices().set_unit_cleaning_rate(
            prop, replace(command, rate_id=uuid4(), unit_id=stray), actor=manager
        )
    with pytest.raises(InvoiceNotFoundError):
        invoices().unit_cleaning_rate(prop, stray, actor=manager)
    elsewhere = uuid4()
    with pytest.raises(InvoiceNotFoundError):
        invoices().set_unit_cleaning_rate(
            elsewhere,
            replace(command, rate_id=uuid4()),
            actor=staff(human, elsewhere, "property.manage"),
        )
    other_unit = second_unit(url, human, prop)
    biller = staff(human, prop, "invoices.create")
    assert invoices().unit_cleaning_rate(prop, unit, actor=biller) == first
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(
                "SELECT app.set_unit_cleaning_rate(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, unit, uuid4(), first["id"], -1, "Negative rate"),
            )
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO app.unit_cleaning_rates(id,property_id,unit_id,rate_usd_cents,"
                "supersedes_rate_id,reason,recorded_by,recorded_at,audit_event_id) "
                "SELECT %s,%s,%s,1,%s,'Cross Unit',%s,clock_timestamp(),audit_event_id "
                "FROM app.unit_cleaning_rates WHERE id=%s",
                (uuid4(), prop, other_unit, first["id"], human, first["id"]),
            )
    assert invoices().unit_cleaning_rate(prop, unit, actor=manager) == first
    assert invoices().unit_cleaning_rate(prop, other_unit, actor=manager) is None


def test_cleaning_functions_refuse_an_inactive_actor(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, lease, unit = moved_out_lease(url)
    rate = set_rate(prop, unit, staff(human, prop), 2_000)
    disabled = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
            "lifecycle_state,mfa_policy_class,provenance) "
            "VALUES (%s,%s,'Disabled Cleaner','Disabled Cleaner','active','optional','test')",
            (disabled, f"cleaning-disabled-{disabled}"),
        )
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (disabled,),
        )
    calls = (
        (
            runtime_database_url(),
            "SELECT app.set_unit_cleaning_rate(%s,%s,%s,%s,%s,%s,%s)",
            (prop, disabled, unit, uuid4(), UUID(str(rate["id"])), 2_100, "Disabled change"),
        ),
        (
            runtime_database_url(),
            "SELECT app.unit_cleaning_rate_current(%s,%s,%s)",
            (prop, disabled, unit),
        ),
        (
            financial_database_url(),
            "SELECT app.record_unit_cleaning_charge(%s,%s,%s,%s,%s)",
            (prop, disabled, uuid4(), lease, UUID(str(rate["id"]))),
        ),
    )
    for database, query, parameters in calls:
        with psycopg.connect(database) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(query, parameters)
        assert refused.value.sqlstate == "P4506", query
    with pytest.raises(InvoiceAuthorizationError):
        invoices().unit_cleaning_rate(prop, unit, actor=staff(disabled, prop))
    assert cleaning_rows(url, lease) == (0, 0)
    assert invoices().unit_cleaning_rate(prop, unit, actor=staff(human, prop)) == rate


def test_cleaning_functions_and_tables_are_least_privilege(migrated_database_url: str) -> None:
    assert migrated_database_url
    record = "app.record_unit_cleaning_charge(uuid,uuid,uuid,uuid,uuid)"
    set_function = "app.set_unit_cleaning_rate(uuid,uuid,uuid,uuid,uuid,bigint,text)"
    read = "app.unit_cleaning_rate_current(uuid,uuid,uuid)"
    internal = (
        "app.unit_cleaning_rate_snapshot(uuid)",
        "app.unit_cleaning_charge_snapshot(uuid)",
    )
    for url, allowed in (
        (runtime_database_url(), {set_function, read}),
        (financial_database_url(), {record}),
    ):
        with psycopg.connect(url) as connection:
            for function in (record, set_function, read, *internal):
                row = connection.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)
                ).fetchone()
                assert row == (function in allowed,), (url, function)
            for table in ("app.unit_cleaning_rates", "app.unit_cleaning_charges"):
                row = connection.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT'),"
                    "has_table_privilege(current_user,%s,'INSERT')",
                    (table, table),
                ).fetchone()
                assert row == (False, False), (url, table)


def test_unit_cleaning_charge_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261016_81")
    assert revision is not None and revision.down_revision == "20261015_80"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
