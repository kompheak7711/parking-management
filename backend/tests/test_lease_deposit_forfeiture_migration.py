"""V1-056 slice 6: Lease Deposit forfeiture drafts and the unpaid-Initial resolution fixes."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from deposit_disposition_test_support import terminate_for_disposition
from payment_test_support import seed_deposit_payment, seed_payment
from property_rental.billing import PostgresRentBillingService, month_end
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    LeaseDepositDraftRequired,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseSignCommand,
    PostgresLeaseService,
)
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureKeyReused,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
    RecordLeaseDepositForfeitureCommand,
    lease_deposit_forfeiture_draft_id,
)
from property_rental.lease_enforcement import (
    NonpaymentEventKind,
    RecordLeaseWarning,
    enforcement_request_digest,
)
from property_rental.lease_termination import TerminationBasis
from property_rental.physical_move_out import PhysicalMoveOutResolutionReliance
from property_rental.unpaid_initial_termination import ResolveNeverMovedInCommand
from termination_test_support import approved_test_termination_context
from test_billing_service_migration import add_service, authenticated, initial_command
from test_deposit_migration import deposit_actor
from test_hand_back_rent_migration import (
    AUGUST,
    correct_move_out,
    hand_back,
    lease_with_invoices,
    raw_resolve,
    version,
)
from test_hand_back_rent_migration import hand_back_database as hand_back_database
from test_invoice_migration import create_recurring_rent_invoice, financial_database_url
from test_lease_lifecycle_migration import actor, draft_command, signature_command
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_rent_nonpayment_recurring_only_migration import enforcement, open_case
from test_rent_nonpayment_recurring_only_migration import record as record_nonpayment_event
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)
from test_termination_deposit_migration import setup_deposits
from test_termination_deposit_migration import terminate as terminate_voluntary
from test_unpaid_initial_termination_migration import (
    ALL,
    PHNOM_PENH,
    row,
    service,
    signed_with_initial,
)
from test_unpaid_initial_termination_migration import terminate as terminate_unpaid


@pytest.fixture
def disposable_database(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """V1 has one Property per database; Service calendars need their own database."""
    assert migrated_database_url
    with _temporary_migration_database("deposit_forfeiture") as temporary:
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        database = conninfo_to_dict(temporary)["dbname"]
        monkeypatch.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=database)
        )
        monkeypatch.setenv(
            "APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=database)
        )
        yield temporary


def signed_with_initial_and_trash(url: str, start_offset: int) -> dict[str, Any]:
    """As the unpaid-Initial fixture, with a Trash Collection line on the Initial Invoice."""
    with psycopg.connect(url) as connection:
        actor_id, prop, unit, customer = setup_reservation_sources(connection)
        _, ids = create_reservation(
            connection,
            actor_id=actor_id,
            property_id=prop,
            unit_id=unit,
            customer_id=customer,
            expiration_days=10,
        )
        today = reservation_business_date(connection, prop)
    start = today - timedelta(days=start_offset)
    end = month_end(start + timedelta(days=365))
    leases = PostgresLeaseService(runtime_database_url(), prop, actor_id)
    who = actor(actor_id, prop, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY)
    draft = draft_command(unit, customer, start_date=start, end_date=end)
    leases.draft(draft, actor=who)
    leases.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    leases.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=2,
            signed_at=datetime.now(UTC),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=ids["reservation_id"],
        ),
        actor=who,
    )
    with psycopg.connect(url) as connection:
        add_service(
            connection,
            actor_id=actor_id,
            property_id=prop,
            lease_id=draft.lease_id,
            code="TRASH_COLLECTION",
            display_name="Trash Collection",
            first_rate=1_000,
            second_rate=1_000,
            approval_from=start,
            approval_through=end,
            applicable_from=start,
            applicable_through=end,
            first_rate_effective=start,
            second_rate_effective=end,
        )
    issued = PostgresRentBillingService(financial_database_url(), prop, actor_id).generate(
        initial_command(
            draft.lease_id,
            uuid4(),
            period_start=start,
            issued_at=datetime(start.year, start.month, start.day, tzinfo=PHNOM_PENH),
        ),
        actor=authenticated(actor_id, prop),
    )
    return {
        "actor": actor_id,
        "property": prop,
        "unit": unit,
        "customer": customer,
        "reservation": ids["reservation_id"],
        "deposit": ids["deposit_id"],
        "lease": draft.lease_id,
        "start": start,
        "today": today,
        "invoice": issued.invoice_id,
    }


def test_never_moved_in_credits_every_unpaid_line_of_a_two_line_initial_invoice(
    disposable_database: str,
) -> None:
    """Q-2026-10-04-10 (a): two lines need a credit Adjustment in one resolution."""
    url = disposable_database
    source = signed_with_initial_and_trash(url, 10)
    with psycopg.connect(url) as connection:
        lines = connection.execute(
            "SELECT id,category,app.invoice_line_outstanding(id) FROM app.invoice_lines "
            "WHERE invoice_id=%s ORDER BY line_sequence",
            (source["invoice"],),
        ).fetchall()
    # The first period can span two months, so the Initial Invoice may carry more than one
    # Trash Collection line; every line with an unpaid rest needs its own credit Adjustment.
    categories = [str(category) for _, category, _ in lines]
    assert categories[0] == "RENT" and "SERVICE_CHARGES" in categories[1:]
    rent, _, rent_outstanding = lines[0]
    assert int(rent_outstanding) > 1_000
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=source["actor"],
            property_id=source["property"],
            customer_id=source["customer"],
            amount=1_000,
        )
    allocation_service().post(
        source["property"],
        payment,
        allocation_designated(source["invoice"], rent, 1_000),
        actor=allocation_actor(source["actor"], source["property"]),
    )
    expected = {
        line: int(outstanding) - (1_000 if line == rent else 0)
        for line, _, outstanding in lines
        if int(outstanding) - (1_000 if line == rent else 0) > 0
    }
    assert len(expected) >= 2
    event = terminate_unpaid(url, source)
    result = service(source).resolve_never_moved_in(
        ResolveNeverMovedInCommand(uuid4(), uuid4(), event, "VACANT", "Never moved in, part paid"),
        actor=actor(source["actor"], source["property"], *ALL),
    )
    assert result["credit_usd_cents"] == sum(expected.values())
    adjustments = result["adjustment_ids"]
    assert isinstance(adjustments, list) and len(adjustments) == len(expected)
    assert row(
        url,
        "SELECT status,app.invoice_application_status(id) FROM app.invoices WHERE id=%s",
        source["invoice"],
    ) == ("PAID", "PAID")
    with psycopg.connect(url) as connection:
        assert (
            dict(
                connection.execute(
                    "SELECT invoice_line_id,amount_usd_cents FROM app.invoice_adjustments "
                    "WHERE invoice_id=%s",
                    (source["invoice"],),
                ).fetchall()
            )
            == expected
        )


def staff(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in capabilities or ("deposits.dispose", "financial.approve")
        ),
    )


def forfeitures() -> LeaseDepositForfeitureService:
    return LeaseDepositForfeitureService(financial_database_url())


def held(url: str, deposit: UUID) -> int:
    return int(row(url, "SELECT app.deposit_held_value_at(%s,statement_timestamp())", deposit)[0])


def forfeited(url: str, deposit: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT d.amount_usd_cents,c.governing_rule FROM app.deposit_dispositions d "
            "JOIN app.lease_deposit_disposition_contexts c ON c.disposition_id=d.id "
            "WHERE d.deposit_id=%s",
            (deposit,),
        ).fetchall()


def draft(prop: UUID, human: UUID, deposit: UUID, **actor: Any) -> dict[str, object]:
    return forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), deposit, uuid4(), "Deposit kept"),
        actor=actor.get("who") or staff(human, prop, "deposits.dispose"),
    )


def raw_record(prop: UUID, human: UUID, deposit: UUID) -> object:
    with psycopg.connect(financial_database_url()) as connection:
        found = connection.execute(
            "SELECT app.record_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s,%s,%s)",
            (prop, human, uuid4(), deposit, uuid4(), "Deposit kept", "deposits.dispose"),
        ).fetchone()
    assert found is not None
    return found[0]


def terminate_on(
    url: str,
    human: UUID,
    prop: UUID,
    lease: UUID,
    day: date,
    governing: str,
    basis: TerminationBasis,
    *,
    warnings: bool,
) -> UUID:
    """Terminate with an explicit governing rule and basis; violation cases carry warnings."""
    with psycopg.connect(url) as connection:
        warning_ids = []
        if warnings:
            for number in range(1, 4):
                warning = RecordLeaseWarning(
                    uuid4(),
                    number,
                    day,
                    day,
                    "Documented signed-Lease violation",
                    "Signed Lease section 18",
                    "Written warning delivered",
                    "Record the documented violation",
                )
                intent = warning.intent()
                found = connection.execute(
                    "SELECT app.lease_enforcement_command(%s,%s,NULL,%s,'WARNING',%s,%s,%s,%s)",
                    (
                        prop,
                        lease,
                        human,
                        warning.idempotency_key,
                        enforcement_request_digest("WARNING", prop, lease, None, intent),
                        Jsonb(intent),
                        "forfeiture-warning",
                    ),
                ).fetchone()
                assert found is not None and isinstance(found[0], dict)
                warning_ids.append(UUID(found[0]["body"]["data"]["id"]))
        context = approved_test_termination_context(basis, warning_ids=tuple(warning_ids))
        current = connection.execute(
            "SELECT version,clock_timestamp() FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert current is not None
        event = uuid4()
        connection.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                uuid4(),
                "b" * 64,
                event,
                lease,
                current[0],
                day,
                current[1],
                governing,
                "Approved termination",
                human,
                Jsonb(context.intent()),
            ),
        )
    return event


def test_voluntary_early_security_forfeiture_is_a_draft_until_an_approver_confirms(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, security, pet, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    amount = held(url, security)
    assert amount > 0
    with pytest.raises(LeaseDepositForfeitureAuthorizationError):
        draft(prop, human, security, who=staff(human, prop, "financial.approve"))
    command = RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Left early")
    preparer = staff(human, prop, "deposits.dispose")
    recorded = forfeitures().record(prop, command, actor=preparer)
    assert forfeitures().record(prop, command, actor=preparer) == recorded
    payload = cast(dict[str, object], recorded["payload"])
    assert (payload["governing_rule"], payload["amount_usd_cents"]) == ("BR-DEP-023", amount)
    assert held(url, security) == amount and forfeited(url, security) == []
    with pytest.raises(LeaseDepositForfeitureConflictError):
        draft(prop, human, security)
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        draft(prop, human, pet)
    draft_id = lease_deposit_forfeiture_draft_id(prop, human, command.idempotency_key)
    with pytest.raises(LeaseDepositForfeitureAuthorizationError):
        forfeitures().confirm(prop, security, draft_id, actor=preparer)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.confirm_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s)",
                (prop, human, security, draft_id, "deposits.dispose"),
            )
    assert refused.value.sqlstate == "42501"
    approver = staff(human, prop, "financial.approve")
    confirmed = forfeitures().confirm(prop, security, draft_id, actor=approver)
    assert forfeitures().confirm(prop, security, draft_id, actor=approver) == confirmed
    assert forfeited(url, security) == [(amount, "BR-DEP-023")]
    assert held(url, security) == 0
    assert row(
        url,
        "SELECT decision,authorization_reference FROM app.financial_draft_decisions "
        "WHERE draft_id=%s",
        draft_id,
    ) == ("CONFIRMED", "financial.approve")


def test_pet_noncompliance_forfeits_both_deposits_through_drafts(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, security, pet, day = setup_deposits(url)
    with psycopg.connect(url) as connection:
        # Receive the Pet Deposit so both deposits hold money to forfeit.
        connection.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
            "occurred_at,actor_id) VALUES (%s,%s,%s,1000,clock_timestamp(),%s)",
            (
                uuid4(),
                pet,
                seed_deposit_payment(connection, deposit_id=pet, actor_id=human, amount=1_000),
                human,
            ),
        )
    service = PostgresDepositService(financial_database_url(), prop, human)
    terminate_for_disposition(url, service, lease, day)
    for deposit in (security, pet):
        amount = held(url, deposit)
        assert amount > 0
        recorded = draft(prop, human, deposit)
        forfeitures().confirm(
            prop,
            deposit,
            UUID(str(recorded["draft_id"])),
            actor=staff(human, prop, "financial.approve"),
        )
        assert forfeited(url, deposit) == [(amount, "BR-DEP-022")]


def test_violation_and_default_grounds_come_from_the_termination_record(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, security, pet, day = setup_deposits(url)
    terminate_on(
        url,
        human,
        prop,
        lease,
        day,
        "BR-LEASE-025",
        TerminationBasis.CUSTOMER_VIOLATION,
        warnings=True,
    )
    amount = held(url, security)
    assert amount > 0
    recorded = draft(prop, human, security)
    assert cast(dict[str, object], recorded["payload"])["governing_rule"] == "BR-LEASE-025"
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="Final Settlement"):
        raw_record(prop, human, pet)
    forfeitures().confirm(
        prop,
        security,
        UUID(str(recorded["draft_id"])),
        actor=staff(human, prop, "financial.approve"),
    )
    assert forfeited(url, security) == [(amount, "BR-LEASE-025")] and held(url, security) == 0

    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_on(
        url,
        human,
        prop,
        lease,
        day,
        "BR-LEASE-028",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    # No Serious Default event is recorded for this Lease, so the ground is refused.
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="cannot be worked out"):
        raw_record(prop, human, security)

    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_on(
        url,
        human,
        prop,
        lease,
        day,
        "Signed Lease other clause",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="cannot be worked out"):
        raw_record(prop, human, security)
    assert forfeited(url, security) == []


def test_unpaid_initial_resolution_no_longer_forfeits_and_the_draft_does(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    amount = held(url, source["deposit"])
    event = terminate_unpaid(url, source)
    service(source).resolve_never_moved_in(
        ResolveNeverMovedInCommand(uuid4(), uuid4(), event, "VACANT", "Never moved in"),
        actor=actor(source["actor"], source["property"], *ALL),
    )
    assert forfeited(url, source["deposit"]) == [] and held(url, source["deposit"]) == amount
    assert amount > 0
    recorded = draft(source["property"], source["actor"], source["deposit"])
    forfeitures().confirm(
        source["property"],
        source["deposit"],
        UUID(str(recorded["draft_id"])),
        actor=staff(source["actor"], source["property"], "financial.approve"),
    )
    assert forfeited(url, source["deposit"]) == [(amount, "BR-LEASE-005")]


def confirm_draft(prop: UUID, human: UUID, deposit: UUID) -> None:
    recorded = draft(prop, human, deposit)
    forfeitures().confirm(
        prop,
        deposit,
        UUID(str(recorded["draft_id"])),
        actor=staff(human, prop, "financial.approve"),
    )


def test_unpaid_initial_security_is_forfeited_also_after_move_in(
    migrated_database_url: str,
) -> None:
    """BR-DEP-026: the BR-LEASE-005 ground holds whether or not the Customer moved in."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
            "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                source["lease"],
                source["customer"],
                source["start"],
                source["actor"],
                source["actor"],
            ),
        )
    terminate_unpaid(url, source)
    amount = held(url, source["deposit"])
    assert amount > 0
    recorded = draft(source["property"], source["actor"], source["deposit"])
    assert cast(dict[str, object], recorded["payload"])["governing_rule"] == "BR-LEASE-005"
    forfeitures().confirm(
        source["property"],
        source["deposit"],
        UUID(str(recorded["draft_id"])),
        actor=staff(source["actor"], source["property"], "financial.approve"),
    )
    assert forfeited(url, source["deposit"]) == [(amount, "BR-LEASE-005")]


def test_thirty_day_default_ground_forfeits_with_a_recorded_serious_default_event(
    migrated_database_url: str,
) -> None:
    """BR-LEASE-028: the 30-day Serious Default event on or before termination is the ground."""
    url = migrated_database_url
    source = signed_with_initial(url, 120)
    human, prop, lease, deposit = (
        source["actor"],
        source["property"],
        source["lease"],
        source["deposit"],
    )
    # A recurring Rent month at least 30 days past its counting day (the 1st, migration 68).
    period = (source["today"] - timedelta(days=35)).replace(day=1)
    with psycopg.connect(url) as connection:
        _, line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=source["customer"],
            lease_id=lease,
            period_start=period,
        )
    flow = enforcement()
    case = open_case(flow, prop, lease, line, human)
    record_nonpayment_event(
        flow, prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT
    )
    terminate_on(
        url,
        human,
        prop,
        lease,
        source["today"],
        "BR-LEASE-028",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    amount = held(url, deposit)
    assert amount > 0
    recorded = draft(prop, human, deposit)
    payload = cast(dict[str, object], recorded["payload"])
    assert (payload["governing_rule"], payload["amount_usd_cents"]) == ("BR-LEASE-028", amount)
    forfeitures().confirm(
        prop,
        deposit,
        UUID(str(recorded["draft_id"])),
        actor=staff(human, prop, "financial.approve"),
    )
    assert forfeited(url, deposit) == [(amount, "BR-LEASE-028")] and held(url, deposit) == 0
    # A Serious Default event of another Lease is no ground for this Lease.
    other_human, other_prop, other_lease, other_security, _, day = setup_deposits(url)
    terminate_on(
        url,
        other_human,
        other_prop,
        other_lease,
        day,
        "BR-LEASE-028",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="cannot be worked out"):
        raw_record(other_prop, other_human, other_security)
    assert forfeited(url, other_security) == []


def decisions(url: str, draft_id: UUID) -> int:
    return int(
        row(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft_id)[
            0
        ]
    )


def test_forfeiture_draft_refusals_change_nothing(migrated_database_url: str) -> None:
    """Key and disposition-id reuse, wrong Property or Deposit, and a stale draft."""
    url = migrated_database_url
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    used = uuid4()
    forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, used, "Left early"),
        actor=staff(human, prop, "deposits.dispose"),
    )
    pending = cast(
        tuple[Any, ...],
        row(
            url,
            "SELECT id FROM app.financial_drafts WHERE payload->>'deposit_id'=%s",
            str(security),
        ),
    )
    forfeitures().confirm(
        prop, security, UUID(str(pending[0])), actor=staff(human, prop, "financial.approve")
    )
    assert [rule for _, rule in forfeited(url, security)] == ["BR-DEP-023"]

    human, prop, lease, security, pet, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    amount = held(url, security)
    preparer = staff(human, prop, "deposits.dispose")
    approver = staff(human, prop, "financial.approve")
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, used, "Left early"),
            actor=preparer,
        )
    command = RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Left early")
    recorded = forfeitures().record(prop, command, actor=preparer)
    draft_id = UUID(str(recorded["draft_id"]))
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(
                command.idempotency_key, security, command.disposition_id, "Changed reason"
            ),
            actor=preparer,
        )
    # The schema holds one Property (properties_singleton_key_unique), so any other Property id
    # is unknown and refused first; the Deposit and draft Property checks stay as defence.
    other = uuid4()
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().record(
            other,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Left early"),
            actor=staff(human, other, "deposits.dispose"),
        )
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm(other, security, draft_id, actor=staff(human, other))
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm(prop, pet, draft_id, actor=approver)
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), uuid4(), uuid4(), "Left early"),
            actor=preparer,
        )
    # A disposition id held by a pending draft is not reused by a draft of another Deposit, and a
    # reason the confirmation would refuse (trailing newline) is refused at the draft.
    third_human, third_prop, third_lease, third_security, _, third_day = setup_deposits(url)
    terminate_voluntary(url, third_human, third_prop, third_lease, third_day)
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record(
            third_prop,
            RecordLeaseDepositForfeitureCommand(
                uuid4(), third_security, command.disposition_id, "Left early"
            ),
            actor=staff(third_human, third_prop, "deposits.dispose"),
        )
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="input is invalid"):
            connection.execute(
                "SELECT app.record_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s,%s,%s)",
                (
                    third_prop,
                    third_human,
                    uuid4(),
                    third_security,
                    uuid4(),
                    "Left early\n",
                    "deposits.dispose",
                ),
            )
    assert forfeited(url, third_security) == []
    assert forfeited(url, security) == [] and held(url, security) == amount
    assert decisions(url, draft_id) == 0
    # A Deposit change after the draft makes it stale: refused, still pending, nothing forfeited.
    PostgresDepositService(financial_database_url(), prop, human).adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            security,
            DepositAdjustmentType.INCREASE,
            1_000,
            day,
            "Approved correction after the draft",
        ),
        actor=deposit_actor(human, prop),
    )
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        forfeitures().confirm(prop, security, draft_id, actor=approver)
    assert forfeited(url, security) == [] and held(url, security) == amount
    assert decisions(url, draft_id) == 0


def test_concurrent_drafts_for_one_deposit_leave_one_pending(migrated_database_url: str) -> None:
    """Only one forfeiture draft per Deposit may wait, also when two are recorded at once."""
    url = migrated_database_url
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    barrier = Barrier(2)

    def attempt(_: int) -> str:
        barrier.wait(timeout=5)
        try:
            draft(prop, human, security)
        except LeaseDepositForfeitureConflictError:
            return "conflict"
        return "recorded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == ["conflict", "recorded"]
    assert row(
        url,
        "SELECT count(*) FROM app.financial_drafts WHERE kind='DEPOSIT_FORFEITURE' "
        "AND payload->>'deposit_id'=%s",
        str(security),
    ) == (1,)
    assert forfeited(url, security) == []


def test_one_call_lease_disposition_and_reversal_are_refused(
    migrated_database_url: str,
) -> None:
    """Owner answers to Q-2026-10-04-12 and Q-2026-10-04-13: drafts only, nothing recorded."""
    url = migrated_database_url
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    service = PostgresDepositService(financial_database_url(), prop, human)
    authority = deposit_actor(human, prop)
    with pytest.raises(LeaseDepositDraftRequired, match="forfeiture draft required"):
        service.record_disposition(
            RecordDepositDispositionCommand(
                uuid4(), uuid4(), security, lease, held(url, security), day, "Left early"
            ),
            actor=authority,
        )
    confirm_draft(prop, human, security)
    disposition = row(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", security)[
        0
    ]
    with pytest.raises(LeaseDepositDraftRequired, match="reversal draft required"):
        service.reverse_disposition(
            ReverseDepositDispositionCommand(
                uuid4(), uuid4(), disposition, "Correct evidence", "CASE-SLICE-6"
            ),
            actor=authority,
        )
    assert row(
        url,
        "SELECT count(*) FROM app.deposit_disposition_reversals WHERE deposit_disposition_id=%s",
        disposition,
    ) == (0,)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.reverse_deposit_disposition_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    uuid4(),
                    "c" * 64,
                    uuid4(),
                    disposition,
                    "Correct evidence",
                    "CASE-SLICE-6",
                    "deposits.correct",
                ),
            )


def test_move_out_correction_is_refused_when_a_hand_back_resolution_relies_on_it(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    first = hand_back(url, scenario, date(2026, 8, 3))
    august = scenario.invoices[AUGUST]
    raw_resolve(scenario, august, "VOID", version(url, august), 80_000)
    resolution = row(
        url, "SELECT id FROM app.hand_back_rent_resolutions WHERE invoice_id=%s", august
    )[0]
    with pytest.raises(PhysicalMoveOutResolutionReliance, match=str(resolution)):
        correct_move_out(url, scenario, first, date(2026, 8, 10))
    assert row(
        url, "SELECT count(*) FROM app.physical_move_out_events WHERE lease_id=%s", scenario.lease
    ) == (1,)


def test_forfeiture_functions_are_least_privilege(migrated_database_url: str) -> None:
    assert migrated_database_url
    record = "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
    confirm = "app.confirm_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,text)"
    source = "app.lease_deposit_forfeiture_source(uuid,uuid)"
    # Retired one-call paths (owner answers to Q-2026-10-04-12 and Q-2026-10-04-13).
    retired = (
        "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,"
        "text,text)",
        "app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,"
        "bigint,date,text,text,uuid,text,bigint)",
        "app.reverse_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,text,text,text)",
    )
    for url, allowed in (
        (runtime_database_url(), set()),
        (financial_database_url(), {record, confirm}),
    ):
        with psycopg.connect(url) as connection:
            for function in (record, confirm, source, *retired):
                found = connection.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)
                ).fetchone()
                assert found == (function in allowed,), (url, function)
    with psycopg.connect(runtime_database_url()) as connection:
        for function in (record, confirm, source, *retired):
            assert connection.execute(
                "SELECT has_function_privilege('prm_bootstrap',%s,'EXECUTE'),"
                "has_function_privilege('public',%s,'EXECUTE')",
                (function, function),
            ).fetchone() == (False, False), function


def test_lease_deposit_forfeiture_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261018_83")
    assert revision is not None and revision.down_revision == "20261017_82"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
