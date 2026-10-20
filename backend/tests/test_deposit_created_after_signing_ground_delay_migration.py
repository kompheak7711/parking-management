"""A Security Deposit created after signing counts for the unpaid-Initial ground only five days
after its creation (V1-056 sub-slice 10i-4a).

Owner answer (a) to Q-2026-10-20-148 (BR-LEASE-005, BR-DEP-004, DL-066): the first amount of a
Security Deposit created after the Lease was signed (every walk-in Security Deposit) counts for
the unpaid-Initial termination ground only on a termination business date after its creation date
plus five days (Asia/Phnom_Penh business dates); a Reservation's Deposit, created before signing,
keeps today's rule. The termination time cannot be later than the database clock, so the later
business dates are checked by direct reads of the ground's internal total. Every Lease here
started ten days ago and has its Initial Rent paid.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService, month_end
from property_rental.deposit import CreateLeaseSecurityDepositCommand, PostgresDepositService
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseSignCommand,
    PostgresLeaseService,
)
from test_billing_service_migration import authenticated, financial_database_url, initial_command
from test_deposit_increase_ground_delay_migration import GROUND_TOTAL, noon
from test_deposit_migration import deposit_actor
from test_deposit_required_total_readers_migration import (
    adjust,
    ground_refused,
    initial_rent_paid,
    record,
    terminate_at,
)
from test_final_settlement_migration import one
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_reservation_migration import reservation_business_date, setup_reservation_sources
from test_settlement_preview_waiting_drafts_migration import STRUCTURE
from test_unpaid_initial_termination_migration import rent_line

REVISION = "20270116_173"
HELPER = "app.deposit_ground_required_total_at(uuid,timestamp with time zone)"
PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
REASON = "Security Deposit total from the signed Lease terms"
HELD = "SELECT app.deposit_held_value_at(%s,'infinity')"
NOW_TOTAL = "SELECT app.deposit_ground_required_total_at(%s,clock_timestamp())"
# A time on the business date `%s` days after the Deposit's creation date (Asia/Phnom_Penh).
AFTER_CREATION = (
    "SELECT timezone('Asia/Phnom_Penh',"
    "(timezone('Asia/Phnom_Penh',created_at)::date+%s)+%s::time) FROM app.deposits WHERE id=%s"
)


def after_creation(url: str, deposit: UUID, days: int, at: str = "12:00") -> Any:
    return one(url, AFTER_CREATION, days, at, deposit)[0]


def walk_in_initial_rent_paid(url: str) -> dict[str, Any]:
    """A walk-in Lease (no Reservation) signed now, started ten days back, its Initial Rent paid
    in full; it has no Security Deposit yet."""
    with psycopg.connect(url) as connection:
        actor_id, prop, unit, customer = setup_reservation_sources(connection)
        today = reservation_business_date(connection, prop)
    start = today - timedelta(days=10)
    leases = PostgresLeaseService(runtime_database_url(), prop, actor_id)
    who = actor(actor_id, prop, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY)
    draft = draft_command(
        unit, customer, start_date=start, end_date=month_end(start + timedelta(days=365))
    )
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
            signed_at=database_now(),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=None,
        ),
        actor=who,
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
    line, outstanding = rent_line(url, issued.invoice_id)
    with psycopg.connect(url) as connection:
        paid_by = seed_payment(
            connection,
            actor_id=actor_id,
            property_id=prop,
            customer_id=customer,
            amount=outstanding,
        )
    allocation_service().post(
        prop,
        paid_by,
        allocation_designated(issued.invoice_id, line, outstanding),
        actor=allocation_actor(actor_id, prop),
    )
    return {
        "actor": actor_id,
        "property": prop,
        "customer": customer,
        "lease": draft.lease_id,
        "today": today,
        "invoice": issued.invoice_id,
    }


def with_walk_in_deposit(url: str) -> dict[str, Any]:
    """The walk-in Lease's Security Deposit is created now on the real path with a 50,000 total
    and takes a 10,000 first receipt through the receipt writer."""
    source = walk_in_initial_rent_paid(url)
    human, prop = source["actor"], source["property"]
    created = PostgresDepositService(
        financial_database_url(), prop, human
    ).create_lease_security_deposit(
        CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), source["lease"], 50_000, REASON),
        actor=deposit_actor(human, prop),
    )
    deposit: UUID = created.deposit_id
    record(url, human, prop, deposit, 10_000)
    source["deposit"] = deposit
    assert one(
        url,
        "SELECT deposit.required_usd_cents,deposit.reservation_id IS NULL,"
        "deposit.created_at>lease.signed_at FROM app.deposits deposit "
        "JOIN app.leases lease ON lease.id=deposit.lease_id WHERE deposit.id=%s",
        deposit,
    ) == (50_000, True, True)
    assert one(url, HELD, deposit) == (10_000,)
    return source


def test_a_deposit_created_after_signing_counts_only_after_its_creation_date_plus_five_days(
    migrated_database_url: str,
) -> None:
    """The Q-148 example on the real path: the walk-in Lease started ten days ago and its
    Security Deposit (50,000 total, 10,000 held) is created today. The ground reads 0 for it
    today and on the business date five days after its creation, so the unpaid-Initial
    termination is refused; from the sixth day it reads the whole 50,000."""
    url = migrated_database_url
    source = with_walk_in_deposit(url)
    deposit = source["deposit"]
    assert one(url, NOW_TOTAL, deposit) == (0,)
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 5)) == (0,)
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 5, "23:59:59.999999")) == (
        0,
    )
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 6, "00:00")) == (50_000,)
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 6)) == (50_000,)
    assert one(url, "SELECT app.deposit_required_total_at(%s,'infinity')", deposit) == (50_000,)
    ground_refused(url, source)


def test_adjustments_of_such_a_deposit_keep_their_own_rules(migrated_database_url: str) -> None:
    """A 20,000 decrease counts at once and a 5,000 increase only after its own five days, both
    recorded today beside the first amount that does not count yet: the ground reads -20,000
    today and on the fifth day (never met) and 35,000 from the sixth (50,000 - 20,000 + 5,000)."""
    url = migrated_database_url
    source = with_walk_in_deposit(url)
    human, prop, deposit = source["actor"], source["property"], source["deposit"]
    adjust(url, human, prop, deposit, 20_000, decrease=True)
    adjust(url, human, prop, deposit, 5_000)
    assert one(url, NOW_TOTAL, deposit) == (-20_000,)
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 5)) == (-20_000,)
    assert one(url, GROUND_TOTAL, deposit, after_creation(url, deposit, 6)) == (35_000,)
    assert one(url, "SELECT app.deposit_required_total_at(%s,'infinity')", deposit) == (35_000,)
    ground_refused(url, source)


def walk_in_deposit_dated(url: str, source: dict[str, Any], days: int) -> UUID:
    """A walk-in Security Deposit row (50,000 total) written by hand with its creation time at
    noon `days` from today, then a 10,000 receipt through the receipt writer. The create stamps
    its own statement time, so the real path cannot date a Deposit days ago; a creation time
    before the signing is also the shape a create statement takes when it starts before a
    signing that commits while it waits (review round 1, security)."""
    deposit = uuid4()
    created = noon(url, days)
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,lease_id,"
            "pet_approval_id,required_usd_cents,required_effective_date,created_by,updated_by,"
            "created_at,updated_at) VALUES (%s,'SECURITY',%s,NULL,%s,NULL,50000,%s,%s,%s,%s,%s)",
            (
                deposit,
                source["customer"],
                source["lease"],
                source["today"],
                source["actor"],
                source["actor"],
                created,
                created,
            ),
        )
    record(url, source["actor"], source["property"], deposit, 10_000)
    assert one(
        url,
        "SELECT deposit.created_at<lease.signed_at,app.deposit_held_value_at(deposit.id,"
        "'infinity') FROM app.deposits deposit JOIN app.leases lease "
        "ON lease.id=deposit.lease_id WHERE deposit.id=%s",
        deposit,
    ) == (True, 10_000)
    return deposit


def test_a_walk_in_deposit_dated_before_signing_still_waits_its_five_days(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security): a Deposit with no Reservation always waits its five days, also
    when its creation time is before the signing. A walk-in Deposit dated five days ago reads 0
    today, so the termination is refused; another walk-in Lease's Deposit dated six days ago
    reads its whole 50,000 with 10,000 held, so its termination is recorded."""
    url = migrated_database_url
    waiting = walk_in_initial_rent_paid(url)
    deposit = walk_in_deposit_dated(url, waiting, -5)
    assert one(url, NOW_TOTAL, deposit) == (0,)
    ground_refused(url, waiting)
    counted = walk_in_initial_rent_paid(url)
    deposit = walk_in_deposit_dated(url, counted, -6)
    assert one(url, NOW_TOTAL, deposit) == (50_000,)
    terminate_at(url, counted)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", counted["lease"]) == (
        "TERMINATED",
    )


def test_a_reservation_deposit_still_counts_for_the_ground_at_once(
    migrated_database_url: str,
) -> None:
    """A Reservation's Security Deposit is created before signing and keeps today's rule: its
    50,000 first amount counts at once, 10,000 is held, and the termination is recorded."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    deposit = source["deposit"]
    assert one(
        url,
        "SELECT deposit.reservation_id IS NOT NULL,deposit.created_at<=lease.signed_at "
        "FROM app.deposits deposit JOIN app.leases lease ON lease.id=deposit.lease_id "
        "WHERE deposit.id=%s",
        deposit,
    ) == (True, True)
    assert one(url, NOW_TOTAL, deposit) == (50_000,)
    terminate_at(url, source)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("TERMINATED",)


def test_the_created_after_signing_ground_delay_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the body of the ground's internal total (owner, privileges,
    definer flag and settings kept; still no EXECUTE for the runtime, financial or bootstrap
    role); no function is added or removed and no trigger, relation, column, privilege or
    constraint changes; the migration is forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270115_172"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(found[0]): tuple(found[1:])
                for found in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            triggers = {
                ":".join(str(item) for item in found)
                for found in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text,"
                    "pg_catalog.pg_get_triggerdef(t.oid) "
                    "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
            structure = {
                ":".join(str(item) for item in found)
                for query in STRUCTURE
                for found in connection.execute(query).fetchall()
            }
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, HELPER)
                ).fetchone() == (False,)
        return functions, triggers, structure

    with _temporary_migration_database("deposit_created_after_signing_ground_delay") as temporary:
        alembic_command.upgrade(config, "20270115_172")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {HELPER}
    assert after_functions[HELPER][1:] == before_functions[HELPER][1:]
    helper = str(after_functions[HELPER][0])
    assert helper.count("deposit.created_at<=lease.signed_at") == 1
    assert (
        helper.count("(deposit.reservation_id IS NOT NULL AND deposit.created_at<=lease.signed_at)")
        == 1
    )
    assert helper.count("LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id") == 1
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
