"""Hand-back month Rent Invoices (BR-RENT-030, BR-RENT-026; owner answers Q-2026-10-04-8 and -9)."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceIdempotencyKeyReused,
    InvoiceVersionConflict,
    PostgresInvoiceService,
    ResolveHandBackRentCommand,
)
from property_rental.lease import PostgresLeaseService
from property_rental.lease_notices import PostgresLeaseNoticeService, RecordLeaseNotice
from property_rental.physical_move_out import EndedOccupancy, RecordPhysicalMoveOut
from test_billing_service_migration import (
    _processed_final_month_request,
    add_service,
    authenticated,
    initial_command,
)
from test_credit_application_migration import designated as credit_designated
from test_credit_migration import actor as credit_actor
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_migration import create_draft, setup_sources
from test_lease_termination import context_without_notice
from test_lease_termination_migration import termination_actor, termination_command
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import actor as payment_actor
from test_payment_allocation_migration import designated as payment_designated
from test_payment_allocation_migration import service as payments
from test_physical_move_out_migration import record as record_move_out
from test_termination_deposit_migration import terminate

AUGUST = date(2026, 8, 1)
SEPTEMBER = date(2026, 9, 1)
MOVE_IN = date(2026, 7, 1)
LEASE_END = date(2027, 1, 31)
# A physical move-out may not precede the Lease signing date, so sign before the fixed dates.
SIGNED_AT = datetime(2026, 6, 20, 9, tzinfo=UTC)


@dataclass(frozen=True)
class Scenario:
    human: UUID
    prop: UUID
    customer: UUID
    lease: UUID
    invoices: dict[date, UUID]
    credit: UUID | None


@pytest.fixture
def hand_back_database(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """V1 has one Property per database; each case gets its own disposable database."""
    assert migrated_database_url
    with _temporary_migration_database("hand_back_rent") as temporary:
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        database = conninfo_to_dict(temporary)["dbname"]
        monkeypatch.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=database)
        )
        monkeypatch.setenv(
            "APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=database)
        )
        yield temporary


def staff(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in capabilities
            or ("invoices.read", "leases.read", "invoices.void", "invoices.adjust")
        ),
    )


def invoices() -> PostgresInvoiceService:
    return PostgresInvoiceService(runtime_database_url(), financial_database_url())


def lease_with_invoices(
    url: str,
    months: tuple[date, ...],
    *,
    trash: bool = False,
    credit: int = 0,
    initial: bool = False,
) -> Scenario:
    """A Lease signed in June and moved in on 1 July 2026 with real monthly Rent Invoices."""
    with psycopg.connect(url) as connection:
        human, prop, unit, customer, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=MOVE_IN,
            end_date=LEASE_END,
            signed=False,
        )
        signer = connection.execute(
            "SELECT id FROM app.lease_signers WHERE lease_id=%s", (lease,)
        ).fetchone()
        assert signer is not None
        connection.execute(
            "SELECT app.sign_draft_lease_signer(%s,%s,%s)", (signer[0], SIGNED_AT, human)
        )
        connection.execute(
            "UPDATE app.leases SET status='SIGNED',signed_at=%s,version=version+1,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (SIGNED_AT, human, lease),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        occupancy = uuid4()
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,"
            "updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (occupancy, lease, customer, MOVE_IN, human, human),
        )
        if trash:
            add_service(
                connection,
                actor_id=human,
                property_id=prop,
                lease_id=lease,
                code="TRASH_COLLECTION",
                display_name="Trash Collection",
                first_rate=1_000,
                second_rate=1_000,
                approval_from=MOVE_IN,
                approval_through=LEASE_END,
                applicable_from=MOVE_IN,
                applicable_through=LEASE_END,
                first_rate_effective=MOVE_IN,
                second_rate_effective=AUGUST,
            )
    credit_identity: UUID | None = None
    if credit:
        # Recognize the Credit before any Invoice makes an obligation due.
        with psycopg.connect(url) as connection:
            paid = seed_payment(
                connection, actor_id=human, property_id=prop, customer_id=customer, amount=credit
            )
        credit_identity = credit_id(recognize(prop, paid, human, credit))
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    generated: dict[date, UUID] = {}
    if initial:
        result = flow.generate(
            initial_command(
                lease,
                occupancy,
                period_start=MOVE_IN,
                issued_at=datetime(2026, 6, 25, 17, tzinfo=UTC),
            ),
            actor=authenticated(human, prop),
        )
        generated[date(2026, 7, 1)] = result.invoice_id
    for month in months:
        result = flow.generate(
            _processed_final_month_request(lease, month), actor=authenticated(human, prop)
        )
        generated[month] = result.invoice_id
    return Scenario(human, prop, customer, lease, generated, credit_identity)


def hand_back(
    url: str,
    scenario: Scenario,
    day: date,
    *,
    voluntary: bool = True,
    terminated_on: date | None = None,
    termination: UUID | None = None,
) -> RecordPhysicalMoveOut:
    """Terminate (on the hand-back date unless given) and record the physical move-out on day."""
    if termination is None:
        termination = terminate(
            url,
            scenario.human,
            scenario.prop,
            scenario.lease,
            terminated_on or day,
            voluntary=voluntary,
        )
    lease_version, unit_version, occupancies = move_out_versions(url, scenario)
    request = RecordPhysicalMoveOut(
        uuid4(),
        uuid4(),
        termination,
        lease_version,
        unit_version,
        day,
        "CLEANING",
        occupancies,
        "Observed departure confirmed",
        "Authorized move-out",
        "Synthetic departure evidence",
    )
    record_move_out(scenario.prop, scenario.lease, scenario.human, request)
    return request


def move_out_versions(url: str, scenario: Scenario) -> tuple[int, int, tuple[EndedOccupancy, ...]]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT l.version,u.version FROM app.leases l JOIN app.units u ON u.id=l.unit_id "
            "WHERE l.id=%s",
            (scenario.lease,),
        ).fetchone()
        assert row is not None
        occupancies = tuple(
            EndedOccupancy(UUID(str(identity)), int(str(version)))
            for identity, version in connection.execute(
                "SELECT id,version FROM app.occupancies WHERE lease_id=%s", (scenario.lease,)
            )
        )
    return int(str(row[0])), int(str(row[1])), occupancies


def correct_move_out(
    url: str, scenario: Scenario, prior: RecordPhysicalMoveOut, day: date
) -> RecordPhysicalMoveOut:
    lease_version, unit_version, occupancies = move_out_versions(url, scenario)
    request = replace(
        prior,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        supersedes_event_id=prior.event_id,
        expected_lease_version=lease_version,
        expected_unit_version=unit_version,
        occupancies=occupancies,
        actual_move_out_date=day,
        evidence_reference="Corrected departure evidence",
    )
    record_move_out(scenario.prop, scenario.lease, scenario.human, request)
    return request


def lines(url: str, invoice: UUID) -> list[tuple[UUID, str, int]]:
    with psycopg.connect(url) as connection:
        return [
            (UUID(str(identity)), str(category), int(str(amount)))
            for identity, category, amount in connection.execute(
                "SELECT id,category,amount_usd_cents FROM app.invoice_lines WHERE invoice_id=%s "
                "ORDER BY line_sequence,id",
                (invoice,),
            )
        ]


def scalar(url: str, query: str, parameters: tuple[object, ...]) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row[0]


def version(url: str, invoice: UUID) -> int:
    return int(str(scalar(url, "SELECT version FROM app.invoices WHERE id=%s", (invoice,))))


def status(url: str, invoice: UUID) -> str:
    return str(scalar(url, "SELECT status FROM app.invoices WHERE id=%s", (invoice,)))


def pay(url: str, scenario: Scenario, invoice: UUID, line: UUID, amount: int) -> None:
    with psycopg.connect(url) as connection:
        paid = seed_payment(
            connection,
            actor_id=scenario.human,
            property_id=scenario.prop,
            customer_id=scenario.customer,
            amount=amount,
        )
    payments().post(
        scenario.prop,
        paid,
        payment_designated(invoice, line, amount),
        actor=payment_actor(scenario.human, scenario.prop),
    )


def resolution_count(url: str, invoice: UUID) -> int:
    return int(
        str(
            scalar(
                url,
                "SELECT count(*) FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
                (invoice,),
            )
        )
    )


def raw_resolve(
    scenario: Scenario,
    invoice: UUID,
    action: str,
    expected_version: int,
    outstanding: int,
    *,
    actor: UUID | None = None,
    prop: UUID | None = None,
) -> dict[str, Any]:
    with psycopg.connect(financial_database_url()) as connection:
        row = connection.execute(
            "SELECT app.resolve_hand_back_rent_invoice(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop or scenario.prop,
                actor or scenario.human,
                invoice,
                uuid4(),
                action,
                expected_version,
                outstanding,
                "Direct",
            ),
        ).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0])


def raw_assess(
    scenario: Scenario, invoice: UUID, *, actor: UUID | None = None, prop: UUID | None = None
) -> dict[str, Any]:
    with psycopg.connect(runtime_database_url()) as connection:
        row = connection.execute(
            "SELECT app.hand_back_rent_invoice_assessment(%s,%s,%s)",
            (prop or scenario.prop, actor or scenario.human, invoice),
        ).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0])


def test_hand_back_before_the_fifth_voids_the_whole_unpaid_invoice_with_its_service_lines(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,), trash=True)
    august = scenario.invoices[AUGUST]
    original = lines(url, august)
    assert [category for _, category, _ in original] == ["RENT", "SERVICE_CHARGES"]
    move_out = hand_back(url, scenario, date(2026, 8, 3)).event_id
    who = staff(scenario.human, scenario.prop)
    assessment = invoices().hand_back_rent_assessment(scenario.prop, august, actor=who)
    assert (
        assessment["coverage"],
        assessment["action"],
        assessment["applied_usd_cents"],
        assessment["outstanding_usd_cents"],
    ) == ("HAND_BACK_MONTH", "VOID", 0, 81_000)
    # An invoices.read holder sees no Lease, move-out or termination identities or dates.
    assert not {"lease_id", "customer_id", "physical_move_out_event_id", "hand_back_date"} & set(
        assessment
    )
    request = ResolveHandBackRentCommand(
        uuid4(),
        "VOID",
        81_000,
        "Customer handed back the Parking on 3 August",
        version(url, august),
    )
    with pytest.raises(InvoiceAuthorizationError):
        invoices().resolve_hand_back_rent(
            scenario.prop,
            august,
            request,
            actor=staff(scenario.human, scenario.prop, "invoices.read", "invoices.adjust"),
        )
    for stale in (
        replace(request, expected_action="CREDIT_ADJUSTMENT"),
        replace(request, expected_outstanding_usd_cents=80_000),
    ):
        with pytest.raises(InvoiceConflictError):
            invoices().resolve_hand_back_rent(scenario.prop, august, stale, actor=who)
    resolved = invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who)
    assert resolved["action"] == "VOID" and resolved["adjustment_ids"] == []
    assert not {"physical_move_out_event_id", "hand_back_date"} & set(resolved)
    assert invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who) == resolved
    with pytest.raises(InvoiceIdempotencyKeyReused):
        invoices().resolve_hand_back_rent(
            scenario.prop, august, replace(request, reason="Another reason"), actor=who
        )
    with pytest.raises(InvoiceIdempotencyKeyReused):
        invoices().resolve_hand_back_rent(scenario.prop, uuid4(), request, actor=who)
    with pytest.raises(InvoiceConflictError) as second:
        invoices().resolve_hand_back_rent(
            scenario.prop,
            august,
            replace(request, idempotency_key=uuid4(), expected_version=version(url, august)),
            actor=who,
        )
    # Exactly the per-Invoice guard (P4503), not a version conflict.
    assert type(second.value) is InvoiceConflictError
    assert status(url, august) == "VOID"
    with psycopg.connect(url) as connection:
        void_event = connection.execute(
            "SELECT id,reason FROM app.invoice_void_events WHERE invoice_id=%s", (august,)
        ).fetchall()
        assert [reason for _, reason in void_event] == [
            "Customer handed back the Parking on 3 August"
        ]
        resolution = connection.execute(
            "SELECT physical_move_out_event_id,hand_back_date,coverage,action,"
            "authorization_reference,expected_outstanding_usd_cents,invoice_void_event_id,"
            "audit_event_id FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
            (august,),
        ).fetchall()
        assert [row[:7] for row in resolution] == [
            (
                move_out,
                date(2026, 8, 3),
                "HAND_BACK_MONTH",
                "VOID",
                "invoices.void",
                81_000,
                void_event[0][0],
            )
        ]
        assert connection.execute(
            "SELECT action,authorization_reference,entity_id,reason FROM app.audit_events "
            "WHERE id=%s",
            (resolution[0][7],),
        ).fetchone() == (
            "invoice.hand_back_rent.resolved",
            "invoices.void",
            august,
            "Customer handed back the Parking on 3 August",
        )
    assert lines(url, august) == original
    for statement in (
        "UPDATE app.hand_back_rent_resolutions SET reason=reason",
        "DELETE FROM app.hand_back_rent_resolutions",
        "TRUNCATE app.hand_back_rent_resolutions",
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(statement)


def test_partly_paid_invoice_keeps_the_paid_part_and_credits_each_unpaid_line(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,), trash=True, credit=400)
    august = scenario.invoices[AUGUST]
    (rent, _, _), (trash, _, _) = lines(url, august)
    pay(url, scenario, august, rent, 20_000)
    assert scenario.credit is not None
    credits().apply(
        scenario.prop,
        scenario.credit,
        credit_designated(august, trash, 400),
        actor=credit_actor(scenario.human, scenario.prop, "credits.apply"),
    )
    move_out = hand_back(url, scenario, date(2026, 8, 4)).event_id
    who = staff(scenario.human, scenario.prop)
    assessment = invoices().hand_back_rent_assessment(scenario.prop, august, actor=who)
    assert (
        assessment["action"],
        assessment["applied_usd_cents"],
        assessment["outstanding_usd_cents"],
    ) == ("CREDIT_ADJUSTMENT", 20_400, 60_600)
    with pytest.raises(InvoiceAuthorizationError):
        invoices().resolve_hand_back_rent(
            scenario.prop,
            august,
            ResolveHandBackRentCommand(uuid4(), "CREDIT_ADJUSTMENT", 60_600, "Unpaid rest", 1),
            actor=staff(scenario.human, scenario.prop, "invoices.read", "invoices.void"),
        )
    before = version(url, august)
    request = ResolveHandBackRentCommand(
        uuid4(), "CREDIT_ADJUSTMENT", 60_600, "Unpaid rest after the 4 August hand-back", before
    )
    resolved = invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who)
    adjustment_ids = [UUID(value) for value in cast(list[str], resolved["adjustment_ids"])]
    assert len(adjustment_ids) == 2
    assert invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who) == resolved
    assert version(url, august) == before + 2
    assert status(url, august) == "PAID"
    resolution = scalar(
        url,
        "SELECT id FROM app.hand_back_rent_resolutions WHERE invoice_id=%s "
        "AND physical_move_out_event_id=%s",
        (august, move_out),
    )
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT id,invoice_line_id,adjustment_type,amount_usd_cents,source_reference,reason "
            "FROM app.invoice_adjustments WHERE invoice_id=%s ORDER BY amount_usd_cents DESC",
            (august,),
        ).fetchall() == [
            (
                adjustment_ids[0],
                rent,
                "CREDIT",
                60_000,
                f"hand-back-rent-resolution:{resolution}",
                "Unpaid rest after the 4 August hand-back",
            ),
            (
                adjustment_ids[1],
                trash,
                "CREDIT",
                600,
                f"hand-back-rent-resolution:{resolution}",
                "Unpaid rest after the 4 August hand-back",
            ),
        ]
        assert connection.execute(
            "SELECT app.invoice_line_outstanding(id),"
            "app.invoice_line_payment_value_at(id,'infinity'),"
            "app.invoice_line_credit_value_at(id,'infinity') FROM app.invoice_lines "
            "WHERE invoice_id=%s ORDER BY line_sequence",
            (august,),
        ).fetchall() == [(0, 20_000, 0), (0, 0, 400)]
        assert connection.execute(
            "SELECT action,authorization_reference,adjustment_ids,invoice_void_event_id "
            "FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
            (august,),
        ).fetchall() == [("CREDIT_ADJUSTMENT", "invoices.adjust", adjustment_ids, None)]


def test_after_the_25th_the_next_month_invoice_is_voided_when_unpaid_and_kept_when_paid(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    paid = lease_with_invoices(url, (AUGUST, SEPTEMBER), trash=True)
    unpaid = lease_with_invoices(url, (AUGUST, SEPTEMBER))
    who = staff(paid.human, paid.prop)
    september = paid.invoices[SEPTEMBER]
    for line, _, amount in lines(url, september):
        pay(url, paid, september, line, amount)
    hand_back(url, paid, date(2026, 8, 27))
    hand_back(url, unpaid, date(2026, 8, 25))
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="not covered"):
        raw_resolve(
            paid, paid.invoices[AUGUST], "VOID", version(url, paid.invoices[AUGUST]), 81_000
        )
    kept = invoices().hand_back_rent_assessment(paid.prop, september, actor=who)
    assert (kept["coverage"], kept["action"], kept["outstanding_usd_cents"]) == (
        "NEXT_MONTH",
        "KEEP",
        0,
    )
    for action in ("VOID", "CREDIT_ADJUSTMENT"):
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="kept as issued"):
            raw_resolve(paid, september, action, version(url, september), 1)
    assert resolution_count(url, september) == 0
    assert status(url, september) == "PAID"
    assert (
        scalar(
            url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", (september,)
        )
        == 0
    )
    next_month = unpaid.invoices[SEPTEMBER]
    assessment = invoices().hand_back_rent_assessment(unpaid.prop, next_month, actor=who)
    assert (assessment["coverage"], assessment["action"]) == ("NEXT_MONTH", "VOID")
    invoices().resolve_hand_back_rent(
        unpaid.prop,
        next_month,
        ResolveHandBackRentCommand(
            uuid4(),
            "VOID",
            cast(int, assessment["outstanding_usd_cents"]),
            "Handed back on 25 August",
            version(url, next_month),
        ),
        actor=who,
    )
    assert status(url, next_month) == "VOID"
    assert status(url, unpaid.invoices[AUGUST]) == "UNPAID"


def test_hand_back_uses_the_current_move_out_date_not_the_termination_date(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    who_scenario = lease_with_invoices(url, (AUGUST,))
    # Terminated on the 10th (no exception) but handed back on the 3rd: the 3rd counts.
    hand_back(url, who_scenario, date(2026, 8, 3), terminated_on=date(2026, 8, 10))
    assessment = raw_assess(who_scenario, who_scenario.invoices[AUGUST])
    assert (assessment["coverage"], assessment["action"]) == ("HAND_BACK_MONTH", "VOID")

    corrected = lease_with_invoices(url, (AUGUST,))
    first = hand_back(url, corrected, date(2026, 8, 10))
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="not covered"):
        raw_assess(corrected, corrected.invoices[AUGUST])
    current = correct_move_out(url, corrected, first, date(2026, 8, 2))
    august = corrected.invoices[AUGUST]
    assert raw_assess(corrected, august)["coverage"] == "HAND_BACK_MONTH"
    raw_resolve(corrected, august, "VOID", version(url, august), 80_000)
    assert (
        scalar(
            url,
            "SELECT physical_move_out_event_id FROM app.hand_back_rent_resolutions "
            "WHERE invoice_id=%s",
            (august,),
        )
        == current.event_id
    )


def test_hand_back_ignores_the_notice_date(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST, SEPTEMBER))
    lease_version = int(
        str(scalar(url, "SELECT version FROM app.leases WHERE id=%s", (scenario.lease,)))
    )
    # A notice dated the 26th would point at September; the hand-back on the 3rd counts.
    notice_day = date(2026, 8, 26)
    notice = RecordLeaseNotice(
        uuid4(),
        uuid4(),
        lease_version,
        notice_day,
        notice_day,
        "Approved actual departure notice",
        "Signed Lease section 18",
        "Approved voluntary departure",
        "Signed surrender terms permit completion on the recorded notice date",
        "Signed notice source",
        "Notice delivered to the Customer",
        "Management notice approval",
        "Record the applicable signed notice",
    )
    PostgresLeaseNoticeService(runtime_database_url(), financial_database_url()).record(
        scenario.prop,
        scenario.lease,
        notice,
        actor=termination_actor(scenario.human, scenario.prop),
        request_id="hand-back-notice",
    )
    context = context_without_notice(
        notice_required=True,
        notice_id=notice.notice_id,
        notice_period_ends_on=notice_day,
        notice_exception_reason=None,
    )
    with psycopg.connect(url) as connection:
        command = termination_command(
            connection, scenario.lease, context=context, actual_date=notice_day
        )
    PostgresLeaseService(runtime_database_url(), scenario.prop, scenario.human).terminate(
        command, actor=termination_actor(scenario.human, scenario.prop)
    )
    hand_back(url, scenario, date(2026, 8, 3), termination=command.event_id)
    august = raw_assess(scenario, scenario.invoices[AUGUST])
    assert (august["coverage"], august["action"]) == ("HAND_BACK_MONTH", "VOID")
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="not covered"):
        raw_assess(scenario, scenario.invoices[SEPTEMBER])


def test_hand_back_rule_refuses_other_terminations_dates_initial_rent_and_stale_input(
    hand_back_database: str,
) -> None:
    url = hand_back_database

    other = lease_with_invoices(url, (AUGUST,))
    hand_back(url, other, date(2026, 8, 3), voluntary=False)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="voluntary early"):
        raw_resolve(other, other.invoices[AUGUST], "VOID", version(url, other.invoices[AUGUST]), 1)

    uncovered: list[UUID] = []
    for day in (date(2026, 8, 5), date(2026, 8, 24)):
        mid_month = lease_with_invoices(url, (AUGUST,))
        hand_back(url, mid_month, day)
        invoice = mid_month.invoices[AUGUST]
        uncovered.append(invoice)
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="not covered"):
            raw_resolve(mid_month, invoice, "VOID", version(url, invoice), 80_000)

    first_month = lease_with_invoices(url, (), initial=True)
    hand_back(url, first_month, date(2026, 7, 3))
    initial = first_month.invoices[date(2026, 7, 1)]
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="only monthly Rent Invoices"):
        raw_resolve(first_month, initial, "VOID", version(url, initial), 1)

    no_move_out = lease_with_invoices(url, (AUGUST,))
    terminate(url, no_move_out.human, no_move_out.prop, no_move_out.lease, date(2026, 8, 2))
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="recorded move-out"):
        raw_resolve(
            no_move_out,
            no_move_out.invoices[AUGUST],
            "VOID",
            version(url, no_move_out.invoices[AUGUST]),
            80_000,
        )

    stale = lease_with_invoices(url, (AUGUST,))
    august = stale.invoices[AUGUST]
    hand_back(url, stale, date(2026, 8, 1))
    who = staff(stale.human, stale.prop)
    assert invoices().hand_back_rent_assessment(stale.prop, august, actor=who)["action"] == "VOID"
    ((rent, _, _),) = lines(url, august)
    pay(url, stale, august, rent, 10_000)
    with pytest.raises(InvoiceVersionConflict):
        invoices().resolve_hand_back_rent(
            stale.prop,
            august,
            ResolveHandBackRentCommand(
                uuid4(), "CREDIT_ADJUSTMENT", 70_000, "Wrong version", version(url, august) + 1
            ),
            actor=who,
        )
    with pytest.raises(InvoiceConflictError):
        invoices().resolve_hand_back_rent(
            stale.prop,
            august,
            ResolveHandBackRentCommand(
                uuid4(), "VOID", 80_000, "Stale action", version(url, august)
            ),
            actor=who,
        )
    for capabilities in (("invoices.void",), ("invoices.read",), ("leases.read",)):
        with pytest.raises(InvoiceAuthorizationError):
            invoices().hand_back_rent_assessment(
                stale.prop, august, actor=staff(stale.human, stale.prop, *capabilities)
            )
    elsewhere = uuid4()
    with pytest.raises(psycopg.Error) as missing:
        raw_assess(stale, august, prop=elsewhere)
    assert missing.value.sqlstate == "P4501"
    with pytest.raises(psycopg.Error) as missing:
        raw_resolve(
            stale, august, "CREDIT_ADJUSTMENT", version(url, august), 70_000, prop=elsewhere
        )
    assert missing.value.sqlstate == "P4501"
    disabled = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
            "lifecycle_state,mfa_policy_class,provenance) "
            "VALUES (%s,%s,'Disabled Clerk','Disabled Clerk','active','optional','test')",
            (disabled, f"hand-back-disabled-{disabled}"),
        )
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (disabled,),
        )
    with pytest.raises(psycopg.Error) as refused:
        raw_assess(stale, august, actor=disabled)
    assert refused.value.sqlstate == "P4506"
    with pytest.raises(psycopg.Error) as refused:
        raw_resolve(
            stale, august, "CREDIT_ADJUSTMENT", version(url, august), 70_000, actor=disabled
        )
    assert refused.value.sqlstate == "P4506"
    untouched = [
        other.invoices[AUGUST],
        *uncovered,
        initial,
        no_move_out.invoices[AUGUST],
        august,
    ]
    for invoice in untouched:
        assert resolution_count(url, invoice) == 0, invoice
    assert (
        scalar(
            url,
            "SELECT count(*) FROM app.invoices WHERE id=ANY(%s) AND status='VOID'",
            (untouched,),
        )
        == 0
    )
    assert (
        scalar(
            url,
            "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=ANY(%s)",
            (untouched,),
        )
        == 0
    )


def test_hand_back_functions_and_table_are_least_privilege(migrated_database_url: str) -> None:
    assert migrated_database_url
    assess = "app.hand_back_rent_invoice_assessment(uuid,uuid,uuid)"
    resolve = "app.resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,text)"
    internal = (
        "app.hand_back_rent_invoice_basis(uuid,uuid,uuid)",
        "app.reject_hand_back_rent_resolution_change()",
        "app.validate_hand_back_rent_resolution()",
    )
    for url, allowed in ((runtime_database_url(), {assess}), (financial_database_url(), {resolve})):
        with psycopg.connect(url) as connection:
            for function in (assess, resolve, *internal):
                row = connection.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)
                ).fetchone()
                assert row == (function in allowed,), (url, function)
            row = connection.execute(
                "SELECT has_table_privilege(current_user,"
                "'app.hand_back_rent_resolutions','SELECT'),"
                "has_table_privilege(current_user,'app.hand_back_rent_resolutions','INSERT')"
            ).fetchone()
            assert row == (False, False), url


def test_hand_back_rent_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261017_82")
    assert revision is not None and revision.down_revision == "20261016_81"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
