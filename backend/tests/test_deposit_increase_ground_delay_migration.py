"""An increase counts for the unpaid-Initial ground only five days after its record (V1-056
sub-slice 10i-2).

Owner answer (b) to Q-2026-10-19-138 (BR-LEASE-005, BR-DEP-004, DL-066): an increase of the
required Security Deposit total counts for the unpaid-Initial termination ground only from the
later of Lease Start plus five days and five days after it was recorded (business dates in
Asia/Phnom_Penh); a decrease counts from its record. The required-amount writer stamps its own
clock time, so an increase recorded days ago cannot be made on the real path; those set-ups write
the adjustment row by hand with an earlier time (said at each one). Every Lease here started ten
days ago, has its Initial Rent paid and a 50,000 Security Deposit total.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_deposit_required_total_readers_migration import (
    adjust,
    ground_refused,
    initial_rent_paid,
    record,
    terminate_at,
)
from test_final_settlement_migration import one
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_preview_waiting_drafts_migration import STRUCTURE

REVISION = "20270115_172"
HELPER = "app.deposit_ground_required_total_at(uuid,timestamp with time zone)"
GROUND = (
    "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,"
    "timestamp with time zone,text,text,uuid)"
)
GROUND_TOTAL = "SELECT app.deposit_ground_required_total_at(%s,%s)"
# Noon on the business date `%s` days from today (Asia/Phnom_Penh, the ground's date rule).
NOON = (
    "SELECT timezone('Asia/Phnom_Penh',"
    "(timezone('Asia/Phnom_Penh',statement_timestamp())::date+%s)+time '12:00')"
)


def noon(url: str, days: int) -> Any:
    return one(url, NOON, days)[0]


def increase_dated(url: str, source: dict[str, Any], days: int, amount: int) -> UUID:
    """A required-amount increase written by hand at noon `days` from today: the writer stamps
    its own clock time, so the real path cannot record an increase days ago."""
    adjustment = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_required_amount_adjustments(id,deposit_id,adjustment_type,"
            "amount_usd_cents,effective_date,reason,occurred_at,actor_id,authorization_reference) "
            "VALUES (%s,%s,'INCREASE',%s,%s,'Signed Lease terms correction',%s,%s,"
            "'deposits.manage')",
            (
                adjustment,
                source["deposit"],
                amount,
                source["today"],
                noon(url, days),
                source["actor"],
            ),
        )
    return adjustment


def fully_paid(url: str) -> dict[str, Any]:
    """The Security Deposit takes 40,000 more through the receipt writer: it holds its whole
    50,000 first amount."""
    source = initial_rent_paid(url)
    record(url, source["actor"], source["property"], source["deposit"], 40_000)
    return source


def test_an_increase_counts_only_after_its_business_date_plus_five_days(
    migrated_database_url: str,
) -> None:
    """A 1,000 increase dated five days ago does not count yet (its date plus five days is
    today): the ground reads 50,000, the Deposit holds 50,000, and the termination is refused.
    Another 1,000 increase dated six days ago counts: the ground reads 51,000 (the required total
    is 52,000), 50,000 held is less, and the termination is recorded."""
    url = migrated_database_url
    source = fully_paid(url)
    deposit = source["deposit"]
    increase_dated(url, source, -5, 1_000)
    assert one(url, GROUND_TOTAL, deposit, noon(url, 0)) == (50_000,)
    ground_refused(url, source)
    increase_dated(url, source, -6, 1_000)
    assert one(
        url,
        "SELECT app.deposit_ground_required_total_at(%s,clock_timestamp()),"
        "app.deposit_required_total_at(%s,'infinity'),app.deposit_held_value_at(%s,'infinity')",
        deposit,
        deposit,
        deposit,
    ) == (51_000, 52_000, 50_000)
    terminate_at(url, source)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("TERMINATED",)


def test_an_increase_before_lease_start_plus_five_days_gets_its_own_five_days(
    migrated_database_url: str,
) -> None:
    """The Lease started ten days ago. A 1,000 increase dated seven days ago (Lease Start plus
    three days) does not count on the business date five days after it (two days ago), and counts
    from the day after (yesterday): it also gets five days, not only until Lease Start plus five
    days. Today it counts, so the termination is recorded with 50,000 held of 51,000."""
    url = migrated_database_url
    source = fully_paid(url)
    deposit = source["deposit"]
    increase_dated(url, source, -7, 1_000)
    assert one(url, GROUND_TOTAL, deposit, noon(url, -2)) == (50_000,)
    assert one(url, GROUND_TOTAL, deposit, noon(url, -1)) == (51_000,)
    terminate_at(url, source)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("TERMINATED",)


def test_a_decrease_counts_at_once_also_beside_an_uncounted_increase(
    migrated_database_url: str,
) -> None:
    """The reviewers' correction example on the real path: the Deposit holds 45,000 of its 50,000
    total. A 10,000 increase and a 10,000 decrease are recorded now (a correction). The decrease
    counts at once and the increase only after five days, so the ground reads 40,000 and is not
    met with 45,000 held; six days from now it would read 50,000 and be met. The ground is only
    ever harder to meet, never easier."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    human, prop, deposit = source["actor"], source["property"], source["deposit"]
    record(url, human, prop, deposit, 35_000)
    adjust(url, human, prop, deposit, 10_000)
    adjust(url, human, prop, deposit, 10_000, decrease=True)
    assert one(
        url,
        "SELECT app.deposit_ground_required_total_at(%s,clock_timestamp()),"
        "app.deposit_required_total_at(%s,'infinity'),app.deposit_held_value_at(%s,'infinity')",
        deposit,
        deposit,
        deposit,
    ) == (40_000, 50_000, 45_000)
    ground_refused(url, source)
    assert one(url, GROUND_TOTAL, deposit, noon(url, 6)) == (50_000,)


def test_the_increase_ground_delay_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration adds one internal function with no grant (only its owner may call it) and
    changes only the body of the ground (owner, privileges, definer flag and settings kept), which
    now reads the new total once; no trigger, relation, column, privilege or constraint changes;
    the migration is forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270114_171"
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
            if HELPER in functions:
                for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                    assert connection.execute(
                        "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, HELPER)
                    ).fetchone() == (False,)
        return functions, triggers, structure

    with _temporary_migration_database("deposit_increase_ground_delay") as temporary:
        alembic_command.upgrade(config, "20270114_171")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) - set(before_functions) == {HELPER}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {GROUND}
    assert after_functions[GROUND][1:] == before_functions[GROUND][1:]
    ground = str(after_functions[GROUND][0])
    assert ground.count("app.deposit_ground_required_total_at(deposit.id,p_occurred)") == 1
    assert ground.count("app.deposit_required_total_at(") == 0
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
