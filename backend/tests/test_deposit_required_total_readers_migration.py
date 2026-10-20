"""The adjusted required total in the readers of the first amount (V1-056 sub-slice 10e-2b-4f).

Owner answer (a) to Q-2026-10-18-130: a Deposit's required total is its first amount plus the
adjustments recorded by then (BR-DEP-004), and every reader uses it. The BR-LEASE-005 ground
compares the Security Deposit's held value at the termination time with the total recorded by
that time; the old Reservation move-in (Leases signed before migration 69) counts only active
receipts of the Security Deposit and of each required Pet Deposit, against the current total;
the Reservation read API shows the current total. Every test runs on the real path, to the cent:
the ground after a decrease, an increase that does not count for the ground until five days after
its record (sub-slice 10i-2, owner answer (b) to Q-2026-10-19-138), a termination dated before a
decrease (a known limit of the database function; the routes take the database's time since
sub-slice 10i-1), the old move-in after an
increase, with more held than a decreased total (review round 1: at least the total, not
equal to it), after a reversed Security Deposit receipt and with a required Pet Deposit (also
holding more than a decreased total, review round 2), the Reservation read API, and least
privilege.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_receipt_reversal_test_support import reverse_receipt_through_draft
from payment_test_support import seed_payment
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    PostgresDepositService,
)
from property_rental.lease_termination import TerminationBasis, TerminationContext
from property_rental.move_in import CompleteMoveInCommand, MoveInInvalidError
from property_rental.reservation_api import PostgresReservationResourceFlow
from test_billing_service_migration import financial_database_url
from test_deposit_migration import create_pet, deposit_actor
from test_deposit_receipt_record_migration import allocator, payment, receipt_command
from test_final_settlement_migration import one, today
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url, setup_move_in
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_payment_move_migration import rows
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20270106_163"
HELPER = "app.deposit_required_total_at(uuid,timestamp with time zone)"
GROUND = (
    "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,"
    "timestamp with time zone,text,text,uuid)"
)
MOVE_IN = (
    "app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,integer,"
    "date,jsonb,text,text,uuid)"
)
GROUND_NOT_MET = "Unpaid Initial obligation ground is not met"
NOT_FULLY_PAID = "Required Security Deposit is not fully paid and unlinked"
PET_NOT_FULLY_PAID = "Required Pet Deposit is not fully paid"


def adjust(
    url: str, human: UUID, prop: UUID, deposit: UUID, amount: int, *, decrease: bool = False
) -> None:
    """A required-amount adjustment through the Deposit service (deposits.manage)."""
    PostgresDepositService(financial_database_url(), prop, human).adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit,
            DepositAdjustmentType.DECREASE if decrease else DepositAdjustmentType.INCREASE,
            amount,
            today(url),
            "Signed Lease terms correction",
        ),
        actor=deposit_actor(human, prop),
    )


def record(url: str, human: UUID, prop: UUID, deposit: UUID, amount: int) -> UUID:
    """A new Payment of the Deposit's Customer recorded into it through the receipt writer."""
    paid_by = payment(url, human, deposit, amount)
    return (
        PostgresDepositService(financial_database_url(), prop, human)
        .record_receipt(receipt_command(deposit, paid_by, amount), actor=allocator(human, prop))
        .deposit_receipt_id
    )


def initial_rent_paid(url: str) -> dict[str, Any]:
    """A Lease signed from a Reservation, started 10 days back, its Initial Rent paid in full;
    its Security Deposit holds the 10,000 first receipt of a 50,000 total."""
    source = signed_with_initial(url, 10)
    line, outstanding = rent_line(url, source["invoice"])
    with psycopg.connect(url) as connection:
        paid_by = seed_payment(
            connection,
            actor_id=source["actor"],
            property_id=source["property"],
            customer_id=source["customer"],
            amount=outstanding,
        )
    allocation_service().post(
        source["property"],
        paid_by,
        allocation_designated(source["invoice"], line, outstanding),
        actor=allocation_actor(source["actor"], source["property"]),
    )
    assert one(
        url,
        "SELECT required_usd_cents,app.deposit_held_value_at(id,'infinity'),lease_id "
        "FROM app.deposits WHERE id=%s",
        source["deposit"],
    ) == (50_000, 10_000, source["lease"])
    return source


def terminate_at(url: str, source: dict[str, Any], occurred: datetime | None = None) -> None:
    """The unpaid-Initial termination (BR-LEASE-005) with the given time, or the statement time."""
    context = TerminationContext(
        basis=TerminationBasis.UNPAID_INITIAL_OBLIGATION,
        signed_lease_provision="Standard Lease clause 7.3: unpaid deposit or Initial Rent",
        approved_grounds="Security Deposit unpaid five days after the Lease Start Date",
        management_authorization_reference="Management decision UNPAID-002",
        evidence_reference="Deposit ledger review UNPAID-002",
        notice_required=False,
        notice_exception_reason="The signed clause allows termination without a notice period",
    )
    with psycopg.connect(url) as connection:
        current = connection.execute(
            "SELECT version,statement_timestamp() FROM app.leases WHERE id=%s", (source["lease"],)
        ).fetchone()
        assert current is not None
        connection.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                source["property"],
                uuid4(),
                "c" * 64,
                uuid4(),
                source["lease"],
                int(str(current[0])),
                source["today"],
                occurred or current[1],
                "BR-LEASE-005",
                "Customer did not pay the Security Deposit",
                source["actor"],
                Jsonb(context.intent()),
            ),
        )


def ground_refused(url: str, source: dict[str, Any], occurred: datetime | None = None) -> None:
    with pytest.raises(psycopg.Error) as refused:
        terminate_at(url, source, occurred)
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == ("22023", GROUND_NOT_MET)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("SIGNED",)


def test_the_ground_reads_a_decreased_required_total(migrated_database_url: str) -> None:
    """A 40,000 decrease brings the Security Deposit's total to the 10,000 it holds, so the
    BR-LEASE-005 ground is not met (before this sub-slice it read the 50,000 first amount and
    the Lease could be terminated as if the Deposit were unpaid)."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    adjust(url, source["actor"], source["property"], source["deposit"], 40_000, decrease=True)
    assert one(url, "SELECT app.deposit_required_total_at(%s,'infinity')", source["deposit"]) == (
        10_000,
    )
    ground_refused(url, source)


def test_an_increase_counts_for_the_ground_only_five_days_after_its_record(
    migrated_database_url: str,
) -> None:
    """The Security Deposit takes 40,000 more through the receipt writer (holds 50,000, its
    first amount). A 1,000 increase recorded after a time t0 does not count for a termination
    dated t0 (refused). Owner answer (b) to Q-2026-10-19-138 (sub-slice 10i-2, renamed from
    `test_an_increase_counts_for_the_ground_from_its_record_time`): it does not count for a
    termination now either, because the Customer gets five days to pay it; the required total is
    51,000, but the ground reads 50,000 and is not met (the counting after five days is in
    `test_deposit_increase_ground_delay_migration.py`)."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    record(url, source["actor"], source["property"], source["deposit"], 40_000)
    before = one(url, "SELECT clock_timestamp()")[0]
    assert isinstance(before, datetime)
    adjust(url, source["actor"], source["property"], source["deposit"], 1_000)
    assert one(
        url,
        "SELECT app.deposit_required_total_at(%s,%s),app.deposit_required_total_at(%s,'infinity'),"
        "(app.deposit_snapshot(%s)->>'required_usd_cents')::bigint,"
        "app.deposit_held_value_at(%s,'infinity')",
        source["deposit"],
        before,
        source["deposit"],
        source["deposit"],
        source["deposit"],
    ) == (50_000, 51_000, 51_000, 50_000)
    ground_refused(url, source, before)
    # Sub-slice 10i-2: the increase recorded now counts for the ground only after five days.
    assert one(
        url, "SELECT app.deposit_ground_required_total_at(%s,clock_timestamp())", source["deposit"]
    ) == (50_000,)
    ground_refused(url, source)


def test_a_termination_dated_before_a_decrease_reads_the_earlier_total_known_limit(
    migrated_database_url: str,
) -> None:
    """Known limit (review round 1, security should-fix 2): a 40,000 decrease is recorded after a
    time t0, and a termination entered after it but dated t0 reads the 50,000 total recorded by
    t0, so the ground is met with 10,000 held and the termination is recorded. Since sub-slice
    10i-1 no route can date a termination (the database's own time); only the server's database
    role can still pass an earlier time to the function (the Q-2026-10-14-112 point 2 known
    limit)."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    before = one(url, "SELECT clock_timestamp()")[0]
    assert isinstance(before, datetime)
    adjust(url, source["actor"], source["property"], source["deposit"], 40_000, decrease=True)
    assert one(
        url,
        "SELECT app.deposit_required_total_at(%s,%s),app.deposit_required_total_at(%s,'infinity')",
        source["deposit"],
        before,
        source["deposit"],
    ) == (50_000, 10_000)
    terminate_at(url, source, before)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("TERMINATED",)


def ready(url: str, value: CompleteMoveInCommand) -> CompleteMoveInCommand:
    """The move-in command with fresh keys and the current versions."""
    versions = one(
        url,
        "SELECT reservation.version,lease.version,unit.version FROM app.reservations reservation "
        "JOIN app.leases lease ON lease.id=%s JOIN app.units unit ON unit.id=reservation.unit_id "
        "WHERE reservation.id=%s",
        value.lease_id,
        value.reservation_id,
    )
    return replace(
        value,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        expected_reservation_version=int(versions[0]),
        expected_lease_version=int(versions[1]),
        expected_unit_version=int(versions[2]),
    )


def move_in_refused(url: str, case: tuple[Any, ...], message: str) -> None:
    service, authenticated, value, _ = case
    with pytest.raises(MoveInInvalidError) as refused:
        service.complete(ready(url, value), actor=authenticated)
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("23514", message)
    assert one(
        url, "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s", value.reservation_id
    ) == (0,)
    assert one(url, "SELECT status FROM app.reservations WHERE id=%s", value.reservation_id) == (
        "ACTIVE",
    )


def move_in_completes(url: str, case: tuple[Any, ...]) -> None:
    service, authenticated, value, security = case
    service.complete(ready(url, value), actor=authenticated)
    assert one(
        url, "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s", value.reservation_id
    ) == (1,)
    assert one(url, "SELECT lease_id FROM app.deposits WHERE id=%s", security) == (value.lease_id,)


def test_the_old_move_in_reads_an_increased_required_total(migrated_database_url: str) -> None:
    """The Reservation's Security Deposit holds its 50,000 first amount; after a 5,000 increase
    the old move-in is refused and writes nothing (before this sub-slice it passed); once a
    5,000 receipt is recorded through the writer, the move-in completes."""
    url = migrated_database_url
    case = setup_move_in(url)
    service, _, _, security = case
    adjust(url, service.actor_id, service.property_id, security, 5_000)
    move_in_refused(url, case, NOT_FULLY_PAID)
    record(url, service.actor_id, service.property_id, security, 5_000)
    assert one(url, "SELECT app.deposit_held_value_at(%s,'infinity')", security) == (55_000,)
    move_in_completes(url, case)


def test_the_old_move_in_takes_a_deposit_holding_more_than_a_decreased_total(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 1; a design change): after a 10,000 decrease the
    Security Deposit holds 50,000 of a 40,000 total. It is fully paid, so the old move-in
    completes, as it did before this sub-slice, when the decrease was not read; an equality
    with the current total would have refused it as "not fully paid"."""
    url = migrated_database_url
    case = setup_move_in(url)
    service, _, _, security = case
    adjust(url, service.actor_id, service.property_id, security, 10_000, decrease=True)
    assert one(
        url,
        "SELECT app.deposit_required_total_at(%s,'infinity'),"
        "app.deposit_held_value_at(%s,'infinity')",
        security,
        security,
    ) == (40_000, 50_000)
    move_in_completes(url, case)


def test_the_old_move_in_counts_only_active_receipts(migrated_database_url: str) -> None:
    """The 40,000 second receipt is reversed through the two-step 8r draft: the old move-in no
    longer counts it (before this sub-slice it counted 50,000 and passed with 10,000 held) and
    is refused; a new 40,000 receipt through the writer lets it complete."""
    url = migrated_database_url
    case = setup_move_in(url)
    service, _, _, security = case
    second = one(
        url,
        "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s AND amount_usd_cents=40000",
        security,
    )[0]
    reverse_receipt_through_draft(
        financial_database_url(), service.property_id, service.actor_id, UUID(str(second))
    )
    assert one(url, "SELECT app.deposit_held_value_at(%s,'infinity')", security) == (10_000,)
    move_in_refused(url, case, NOT_FULLY_PAID)
    record(url, service.actor_id, service.property_id, security, 40_000)
    move_in_completes(url, case)


def required_pet_deposit(url: str, case: tuple[Any, ...]) -> tuple[UUID, UUID, UUID]:
    """A pet approved on the move-in date whose signed terms require a Pet Deposit, and that
    20,000 Pet Deposit of the Lease, holding nothing: the actor, the Property and the Deposit."""
    service, _, value, _ = case
    human, prop = service.actor_id, service.property_id
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Approved move-in pet',clock_timestamp(),%s)",
            (approval, value.lease_id, value.actual_move_in_date, human),
        )
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    pet, _ = create_pet(
        deposits, deposit_actor(human, prop), value.lease_id, approval, value.actual_move_in_date
    )
    return human, prop, pet


def test_the_old_move_in_reads_a_pet_deposit_s_active_receipts_and_total(
    migrated_database_url: str,
) -> None:
    """A required 20,000 Pet Deposit whose 20,000 receipt is reversed is not paid (before this
    sub-slice the reversed receipt counted); after a 1,000 increase and a 21,000 receipt the old
    move-in completes (before this sub-slice 21,000 did not equal the 20,000 first amount)."""
    url = migrated_database_url
    case = setup_move_in(url)
    human, prop, pet = required_pet_deposit(url, case)
    first = record(url, human, prop, pet, 20_000)
    reverse_receipt_through_draft(financial_database_url(), prop, human, first)
    move_in_refused(url, case, PET_NOT_FULLY_PAID)
    adjust(url, human, prop, pet, 1_000)
    record(url, human, prop, pet, 21_000)
    assert one(
        url,
        "SELECT app.deposit_required_total_at(%s,'infinity'),"
        "app.deposit_held_value_at(%s,'infinity')",
        pet,
        pet,
    ) == (21_000, 21_000)
    move_in_completes(url, case)


def test_the_old_move_in_takes_a_pet_deposit_holding_more_than_a_decreased_total(
    migrated_database_url: str,
) -> None:
    """Review round 2 (independent should-fix 3): a required 20,000 Pet Deposit holds its 20,000
    receipt after a 5,000 decrease (total 15,000). It is fully paid, so the old move-in completes,
    as it did before this sub-slice; an equality with the current total would refuse it."""
    url = migrated_database_url
    case = setup_move_in(url)
    human, prop, pet = required_pet_deposit(url, case)
    record(url, human, prop, pet, 20_000)
    adjust(url, human, prop, pet, 5_000, decrease=True)
    assert one(
        url,
        "SELECT app.deposit_required_total_at(%s,'infinity'),"
        "app.deposit_held_value_at(%s,'infinity')",
        pet,
        pet,
    ) == (15_000, 20_000)
    move_in_completes(url, case)


def test_the_reservation_read_api_shows_the_adjusted_required_total(
    migrated_database_url: str,
) -> None:
    """Through the runtime role, the Reservation resource shows the 50,000 first amount, then
    51,000 after a 1,000 increase (before this sub-slice it kept showing 50,000)."""
    url = migrated_database_url
    service, _, value, security = setup_move_in(url)
    flow = PostgresReservationResourceFlow(runtime_database_url(), financial_database_url())
    before = flow.get(value.reservation_id)
    assert before.deposit_required_usd_cents == 50_000
    assert before.deposit_received_usd_cents == 50_000
    adjust(url, service.actor_id, service.property_id, security, 1_000)
    after = flow.get(value.reservation_id)
    assert after.deposit_required_usd_cents == 51_000
    assert after.deposit_received_usd_cents == 50_000


def test_the_required_total_readers_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4f adds one internal function that no application role may run (NULL for
    an unknown Deposit or a NULL time) and patches the ground and the old move-in, each by exactly
    its listed replacements, with the same owner, privileges and settings; no other function,
    constraint or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270105_162"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert one(
        migrated_database_url,
        "SELECT bool_and(acl.grantee=p.proowner),p.prosecdef,p.proconfig::text "
        "FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) acl "
        "WHERE p.oid=CAST(%s AS regprocedure) GROUP BY p.prosecdef,p.proconfig",
        HELPER,
    ) == (True, True, "{search_path=pg_catalog}")
    # Review round 1 (security note 6): no application role may run it, directly or by grant,
    # and it has the owner of the two functions that call it.
    assert one(
        migrated_database_url,
        "SELECT bool_or(has_function_privilege(role,CAST(%s AS regprocedure),'EXECUTE')) "
        "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap']) role",
        HELPER,
    ) == (False,)
    assert one(
        migrated_database_url,
        "SELECT count(DISTINCT proowner) FROM pg_catalog.pg_proc "
        "WHERE oid IN (CAST(%s AS regprocedure),CAST(%s AS regprocedure),"
        "CAST(%s AS regprocedure))",
        HELPER,
        GROUND,
        MOVE_IN,
    ) == (1,)
    for database in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(database) as connection, pytest.raises(psycopg.Error) as denied:
            connection.execute(
                "SELECT app.deposit_required_total_at(%s,'infinity')", (uuid4(),)
            ).fetchone()
        assert denied.value.sqlstate == "42501"
    # Review round 1 (both reviewers): its values on a Deposit of this test (a 50,000 first
    # amount and a 1,000 increase): NULL for a NULL time or an unknown Deposit.
    service, _, _, security = setup_move_in(migrated_database_url)
    adjust(migrated_database_url, service.actor_id, service.property_id, security, 1_000)
    assert one(
        migrated_database_url,
        "SELECT app.deposit_required_total_at(%s,NULL),"
        "app.deposit_required_total_at(%s,'-infinity'),"
        "app.deposit_required_total_at(%s,'infinity'),"
        "app.deposit_required_total_at(%s,'infinity')",
        security,
        security,
        security,
        uuid4(),
    ) == (None, 50_000, 51_000, None)

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        others = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT 'constraint',c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app' AND c.contype<>'t' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("deposit_required_total_readers") as temporary:
        alembic_command.upgrade(config, "20270105_162")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) - set(before_functions) == {HELPER}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {GROUND, MOVE_IN}
    for name, replacements in (
        (GROUND, revision.module.GROUND_REPLACEMENTS),
        (MOVE_IN, revision.module.MOVE_IN_REPLACEMENTS),
    ):
        expected = before_functions[name][0]
        for before, after in replacements:
            assert expected.count(before) == 1
            expected = expected.replace(before, after)
        assert after_functions[name][0] == expected
        assert after_functions[name][1:] == before_functions[name][1:]
