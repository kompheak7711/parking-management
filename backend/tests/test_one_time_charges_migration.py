"""Manual Damage and Miscellaneous charges with an issue-time, Property-configured Due Date."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceInvalidError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    RecordOneTimeChargeCommand,
    SetOneTimeChargeDueDaysCommand,
)
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from test_invoice_migration import (
    financial_database_url,
    runtime_database_url,
    setup_invoice_api_source,
)
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_move_out_inspection_migration import source as inspection_source

ALL_CAPABILITIES = (
    "invoices.read",
    "invoices.create",
    "invoices.issue",
    "damage_charges.bill",
    "property.manage",
    # Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): the due days need Settings access.
    "settings.manage",
)


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


def today(url: str) -> date:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
    assert row is not None and isinstance(row[0], date)
    return row[0]


def inspected_lease(
    url: str,
) -> tuple[UUID, UUID, UUID, UUID, RecordMoveOutInspection]:
    """Return human, Property, Lease, primary Customer and the recorded inspection."""
    human, prop, lease, request = inspection_source(url)
    inspection_flow().record(
        prop, lease, request, actor=inspection_actor(human, prop), request_id="inspect"
    )
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
    assert row is not None
    return human, prop, lease, UUID(str(row[0])), request


def damage(customer: UUID, lease: UUID, finding: UUID) -> RecordOneTimeChargeCommand:
    return RecordOneTimeChargeCommand(
        uuid4(),
        "DAMAGE_CHARGES",
        customer,
        lease,
        finding,
        "Replace damaged door",
        12_500,
        "Door broken at move-out",
        "Inspection note 7",
    )


def miscellaneous(customer: UUID) -> RecordOneTimeChargeCommand:
    return RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        None,
        None,
        "Replacement key card",
        1_500,
        "Customer lost key card",
        "Front desk log 12",
    )


def draft_and_issue(prop: UUID, obligation: UUID, who: AuthenticatedActor) -> dict[str, object]:
    service = invoices()
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=who)
    assert draft["due_date"] is None
    return service.issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=who,
    )


def invoice_due(url: str, invoice: object) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT due_date,due_date_rule,due_date_source,due_date_override_reason,"
            "due_date_set_by FROM app.invoices WHERE id=%s",
            (UUID(str(invoice)),),
        ).fetchone()
    assert row is not None
    return row


def property_version(url: str, prop: UUID) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT version FROM app.properties WHERE id=%s", (prop,)
        ).fetchone()
    assert row is not None
    return int(str(row[0]))


def test_damage_charge_bills_one_current_finding_and_is_due_issue_plus_seven(
    migrated_database_url: str,
) -> None:
    human, prop, lease, customer, inspection = inspected_lease(migrated_database_url)
    who = staff(human, prop)
    command = damage(customer, lease, inspection.findings[0].finding_id)
    recorded = invoices().record_one_time_charge(prop, command, actor=who)
    assert recorded["amount_usd_cents"] == 12_500
    assert recorded["due_date_rule"] == "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS"
    assert recorded["authorization_reference"] == "damage_charges.bill"
    assert invoices().record_one_time_charge(prop, command, actor=who) == recorded
    with pytest.raises(InvoiceConflictError):
        invoices().record_one_time_charge(
            prop, replace(command, amount_usd_cents=12_600), actor=who
        )
    with pytest.raises(InvoiceConflictError):
        invoices().record_one_time_charge(prop, replace(command, charge_id=uuid4()), actor=who)
    issued = draft_and_issue(prop, command.charge_id, who)
    issue_day = today(migrated_database_url)
    assert invoice_due(migrated_database_url, issued["id"]) == (
        issue_day + timedelta(days=7),
        "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS",
        "BR-INV-018",
        None,
        None,
    )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.invoices SET due_date=due_date+1 WHERE id=%s",
                (UUID(str(issued["id"])),),
            )
    with psycopg.connect(migrated_database_url) as connection:
        audit = connection.execute(
            "SELECT reason,authorization_reference FROM app.audit_events "
            "WHERE action='invoice.one_time_charge.recorded' AND entity_id=%s",
            (command.charge_id,),
        ).fetchall()
    assert audit == [("Door broken at move-out", "damage_charges.bill")]


def test_damage_requires_capability_and_a_matching_current_finding(
    migrated_database_url: str,
) -> None:
    human, prop, lease, customer, inspection = inspected_lease(migrated_database_url)
    first, second = (finding.finding_id for finding in inspection.findings)
    with pytest.raises(InvoiceAuthorizationError):
        invoices().record_one_time_charge(
            prop, damage(customer, lease, first), actor=staff(human, prop, "invoices.create")
        )
    for wrong in (damage(uuid4(), lease, first), damage(customer, lease, uuid4())):
        with pytest.raises(InvoiceInvalidError):
            invoices().record_one_time_charge(prop, wrong, actor=staff(human, prop))
    correction = replace(
        inspection,
        idempotency_key=uuid4(),
        inspection_id=uuid4(),
        supersedes_inspection_id=inspection.inspection_id,
        result_text="Corrected inspection",
        reason="Correct inspection",
        findings=(InspectionFinding(uuid4(), "Corrected door", False),),
    )
    inspection_flow().record(
        prop, lease, correction, actor=inspection_actor(human, prop), request_id="correct"
    )
    with pytest.raises(InvoiceInvalidError):
        invoices().record_one_time_charge(
            prop, damage(customer, lease, second), actor=staff(human, prop)
        )
    current = invoices().record_one_time_charge(
        prop,
        damage(customer, lease, correction.findings[0].finding_id),
        actor=staff(human, prop, "damage_charges.bill"),
    )
    assert current["inspection_damage_finding_id"] == str(correction.findings[0].finding_id)


def test_miscellaneous_charge_accepts_an_authorized_due_date_with_reason(
    migrated_database_url: str,
) -> None:
    human, prop, _, customer, _ = inspected_lease(migrated_database_url)
    who = staff(human, prop)
    with pytest.raises(InvoiceAuthorizationError):
        invoices().record_one_time_charge(
            prop, miscellaneous(customer), actor=staff(human, prop, "damage_charges.bill")
        )
    command = miscellaneous(customer)
    recorded = invoices().record_one_time_charge(prop, command, actor=who)
    assert recorded["authorization_reference"] == "invoices.create"
    service = invoices()
    draft = service.create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), command.charge_id), actor=who
    )
    invoice = UUID(str(draft["id"]))
    version = cast(int, draft["version"])
    issue_day = today(migrated_database_url)
    with pytest.raises(InvoiceInvalidError):
        service.issue(
            prop,
            invoice,
            IssueInvoiceCommand(uuid4(), version, issue_day - timedelta(days=1), "Backdated"),
            actor=who,
        )
    service.issue(
        prop,
        invoice,
        IssueInvoiceCommand(uuid4(), version, issue_day + timedelta(days=20), "Payroll date"),
        actor=who,
    )
    assert invoice_due(migrated_database_url, invoice) == (
        issue_day + timedelta(days=20),
        "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS",
        "BR-INV-018",
        "Payroll date",
        human,
    )
    with psycopg.connect(migrated_database_url) as connection:
        audit = connection.execute(
            "SELECT reason FROM app.audit_events WHERE action='invoice.issued' AND entity_id=%s",
            (invoice,),
        ).fetchall()
    assert audit == [("Payroll date",)]


def test_due_days_setting_is_authorized_audited_and_never_changes_issued_invoices(
    migrated_database_url: str,
) -> None:
    human, prop, _, customer, _ = inspected_lease(migrated_database_url)
    who = staff(human, prop)
    first = miscellaneous(customer)
    invoices().record_one_time_charge(prop, first, actor=who)
    before = draft_and_issue(prop, first.charge_id, who)
    version = property_version(migrated_database_url, prop)
    change = SetOneTimeChargeDueDaysCommand(10, "Owner policy change", version)
    for refused in ("invoices.issue", "property.manage"):
        with pytest.raises(InvoiceAuthorizationError):
            invoices().set_one_time_charge_due_days(prop, change, actor=staff(human, prop, refused))
    with pytest.raises(InvoiceVersionConflict):
        invoices().set_one_time_charge_due_days(
            prop, replace(change, expected_version=version + 5), actor=who
        )
    changed = invoices().set_one_time_charge_due_days(prop, change, actor=who)
    assert changed["one_time_charge_due_days"] == 10 and changed["version"] == version + 1
    try:
        second = miscellaneous(customer)
        invoices().record_one_time_charge(prop, second, actor=who)
        after = draft_and_issue(prop, second.charge_id, who)
        issue_day = today(migrated_database_url)
        assert invoice_due(migrated_database_url, before["id"])[0] == issue_day + timedelta(days=7)
        assert invoice_due(migrated_database_url, after["id"])[0] == issue_day + timedelta(days=10)
    finally:
        invoices().set_one_time_charge_due_days(
            prop,
            SetOneTimeChargeDueDaysCommand(7, "Restore default", version + 1),
            actor=who,
        )
    with psycopg.connect(migrated_database_url) as connection:
        audit = connection.execute(
            "SELECT reason,previous_state->>'one_time_charge_due_days',"
            "resulting_state->>'one_time_charge_due_days' FROM app.audit_events "
            "WHERE action='property.one_time_charge_due_days.set' AND entity_id=%s "
            "ORDER BY occurred_at",
            (prop,),
        ).fetchall()
    assert audit[-2:] == [("Owner policy change", "7", "10"), ("Restore default", "10", "7")]


def test_governing_source_obligation_keeps_its_recorded_due_date(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, obligation = setup_invoice_api_source(connection)
        governing = connection.execute(
            "SELECT governing_due_date,due_date_rule FROM app.authorized_nonrecurring_obligations "
            "WHERE id=%s",
            (obligation,),
        ).fetchone()
    assert governing is not None and governing[1] == "GOVERNING_SOURCE"
    who = staff(human, prop)
    service = invoices()
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=who)
    invoice = UUID(str(draft["id"]))
    version = cast(int, draft["version"])
    with pytest.raises(InvoiceInvalidError):
        service.issue(
            prop,
            invoice,
            IssueInvoiceCommand(uuid4(), version, governing[0], "Not allowed here"),
            actor=who,
        )
    service.issue(prop, invoice, IssueInvoiceCommand(uuid4(), version), actor=who)
    due, rule, _, override_reason, _ = invoice_due(migrated_database_url, invoice)
    assert (due, rule, override_reason) == (governing[0], "GOVERNING_SOURCE", None)


def test_one_time_charge_storage_constraints_and_command_shapes(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.authorized_nonrecurring_obligations'::regclass"
            )
        }
        default_days = connection.execute(
            "SELECT column_default FROM information_schema.columns WHERE table_schema='app' "
            "AND table_name='properties' AND column_name='one_time_charge_due_days'"
        ).fetchone()
    assert {
        "authorized_nonrecurring_due_date_rule_shape",
        "authorized_nonrecurring_damage_one_time",
        "authorized_nonrecurring_damage_finding_fk",
        "authorized_nonrecurring_damage_finding_once",
    } <= names
    assert "authorized_nonrecurring_damage_source_deferred" not in names
    assert default_days == ("7",)
    customer = uuid4()
    with pytest.raises(ValueError, match="Damage"):
        replace(damage(customer, uuid4(), uuid4()), inspection_damage_finding_id=None)
    with pytest.raises(ValueError, match="Miscellaneous"):
        replace(miscellaneous(customer), inspection_damage_finding_id=uuid4())
    with pytest.raises(ValueError, match="amount_usd_cents"):
        replace(miscellaneous(customer), amount_usd_cents=0)
    with pytest.raises(ValueError, match="together"):
        IssueInvoiceCommand(uuid4(), 1, date(2026, 10, 9))
    with pytest.raises(ValueError, match="days"):
        SetOneTimeChargeDueDaysCommand(0, "Too short", 1)


def test_one_time_charges_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261002_65")
    assert revision is not None and revision.down_revision == "20261001_64"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
