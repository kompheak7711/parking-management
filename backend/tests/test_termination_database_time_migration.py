"""The termination time from the database clock, and the termination locks the Lease's Deposits
(V1-056 sub-slice 10i-1).

Owner answer (a) to Q-2026-10-14-112 point 1 (BR-AUDIT-003): the termination time means the moment
staff save the termination, so the route takes no time and the database stamps its own; a retry of
the same request replays the first result. Owner answer (a) to Q-2026-10-18-133 (BR-LEASE-005,
BR-DEP-023, BR-DEP-026): after the Lease and Unit, the termination locks the Lease's Deposits in id
order, so a required-amount adjustment saved beside a termination and the termination wait for
each other, and the one that comes second reads the first. The receipt case is
`test_a_receipt_beside_an_uncommitted_termination_waits_and_is_refused` in
`test_deposit_receipt_leftover_migration.py`. Review round 1: a termination stamped with the
database's time is refused (40001) when a Deposit event or adjustment of the Lease dated after its
time was saved while it waited for its locks (security should-fix 1); an adjustment is dated after
its Deposit lock (independent note 3); the Pet departure writer locks the Lease before its Pet
Deposit, so it never deadlocks with a termination (independent blocker 1).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.deposit import (
    DepositNotFoundError,
    PostgresDepositService,
    RecordPetDepartureCommand,
)
from property_rental.lease_termination import TerminationBasis, TerminationContext
from termination_test_support import approved_test_termination_context
from test_deposit_migration import create_pet, setup_signed_pet_lease
from test_deposit_receipt_record_migration import allocator, payment, receipt_command
from test_deposit_required_total_readers_migration import (
    GROUND_NOT_MET,
    adjust,
    ground_refused,
    initial_rent_paid,
)
from test_invoice import mutation_headers
from test_invoice_migration import financial_database_url
from test_lease_lifecycle_migration import actor
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_api_migration import api
from test_pet_payback_restoration_refusal_migration import wait_until_blocked_by
from test_settlement_preview_waiting_drafts_migration import STRUCTURE
from test_unpaid_initial_termination_migration import ALL, row, signed_with_initial, terminate_body

REVISION = "20270114_171"
WITH_CONTEXT = (
    "app.terminate_lease_with_context(uuid,uuid,text,uuid,uuid,integer,date,"
    "timestamp with time zone,text,text,uuid,jsonb)"
)
TERMINATE = (
    "app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,"
    "text,uuid)"
)
ADJUST = (
    "app.adjust_deposit_required_amount(uuid,uuid,uuid,text,uuid,uuid,text,bigint,date,text,text)"
)
DEPARTURE = "app.record_active_lease_pet_departure(uuid,uuid,uuid,text,uuid,uuid,date,text,text)"
DEPOSIT_LOCK = "PERFORM 1 FROM app.deposits WHERE lease_id = p_lease_id ORDER BY id FOR UPDATE;"
SAVED_TIME = "v_saved.occurred_at IS DISTINCT FROM p_occurred_at"
CHANGED = "The Lease's Deposits changed while this termination waited; record it again"
LEASE_FIRST = "WHERE deposit.id=p_deposit_id FOR KEY SHARE OF lease;"
TERMINATE_NOW = (
    "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),"
    "%s,%s,%s,%s)"
)
UNPAID_INITIAL = TerminationContext(
    basis=TerminationBasis.UNPAID_INITIAL_OBLIGATION,
    signed_lease_provision="Standard Lease clause 7.3: unpaid deposit or Initial Rent",
    approved_grounds="Security Deposit unpaid five days after the Lease Start Date",
    management_authorization_reference="Management decision UNPAID-002",
    evidence_reference="Deposit ledger review UNPAID-002",
    notice_required=False,
    notice_exception_reason="The signed clause allows termination without a notice period",
)


def unpaid_initial_now(url: str, source: dict[str, Any]) -> tuple[str, str]:
    """The unpaid-Initial termination stamped with the database's own time (the route's path), in
    its own connection: its outcome after its commit."""
    try:
        with psycopg.connect(url) as connection:
            current = connection.execute(
                "SELECT version FROM app.leases WHERE id=%s", (source["lease"],)
            ).fetchone()
            assert current is not None
            connection.execute(
                TERMINATE_NOW,
                (
                    source["property"],
                    uuid4(),
                    "e" * 64,
                    uuid4(),
                    source["lease"],
                    current[0],
                    source["today"],
                    "BR-LEASE-005",
                    "Customer did not pay the Security Deposit",
                    source["actor"],
                    Jsonb(UNPAID_INITIAL.intent()),
                ),
            )
    except psycopg.Error as error:
        return str(error.sqlstate), str(error.diag.message_primary)
    return "committed", ""


def test_http_termination_time_is_the_database_time(migrated_database_url: str) -> None:
    """Through the route and the runtime role: a body that still sends a termination time is
    refused (422) and the Lease does not change; without one, the Lease's `terminated_at` is the
    statement time, the same value the database stamps on the termination context row; a retry
    with the same Idempotency-Key and body returns the first result and writes no second row."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    who = actor(source["actor"], source["property"], *ALL)
    path = f"/api/v1/leases/{source['lease']}/terminate"
    version = int(row(url, "SELECT version FROM app.leases WHERE id=%s", source["lease"])[0])
    body = terminate_body(url, source)

    refused = api(who).post(
        path,
        json={**body, "occurred_at": "2026-01-01T00:00:00Z"},
        headers=mutation_headers(version=version),
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["fields"] == ["body.occurred_at"]
    assert row(url, "SELECT status,version FROM app.leases WHERE id=%s", source["lease"]) == (
        "SIGNED",
        version,
    )

    key = uuid4()
    reply = api(who).post(path, json=body, headers=mutation_headers(key=key, version=version))
    assert reply.status_code == 200, reply.text
    stamped = row(
        url,
        "SELECT lease.terminated_at,context.recorded_at,lease.terminated_at=context.recorded_at "
        "FROM app.leases lease JOIN app.lease_termination_contexts context "
        "ON context.lease_id=lease.id WHERE lease.id=%s",
        source["lease"],
    )
    assert stamped[2] is True

    replay = api(who).post(path, json=body, headers=mutation_headers(key=key, version=version))
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"] == reply.json()["data"]
    assert row(
        url,
        "SELECT count(*),min(lease.terminated_at) FROM app.lease_termination_contexts context "
        "JOIN app.leases lease ON lease.id=context.lease_id WHERE context.lease_id=%s",
        source["lease"],
    ) == (1, stamped[0])


def test_a_termination_waits_for_a_decrease_being_saved_and_reads_it(
    migrated_database_url: str,
) -> None:
    """A 40,000 decrease (the 50,000 total down to the 10,000 held) is saved in an open
    transaction, which holds the Security Deposit's lock. An unpaid-Initial termination waits for
    it and, after its commit, reads the decrease: the ground is not met (22023) and the Lease stays
    signed. Before this sub-slice the termination did not wait, read the 50,000 total and was
    recorded (10e-2b-4f security note 3)."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    with psycopg.connect(url) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.execute(
            "SELECT app.adjust_deposit_required_amount(%s,%s,%s,%s,%s,%s,'DECREASE',40000,"
            "%s,'Signed Lease terms correction','deposits.manage')",
            (
                source["property"],
                source["actor"],
                uuid4(),
                "d" * 64,
                uuid4(),
                source["deposit"],
                source["today"],
            ),
        )
        waiting = pool.submit(ground_refused, url, source)
        try:
            wait_until_blocked_by(url, holder)
            assert not waiting.done()
        finally:
            holder.commit()
        waiting.result(timeout=60)
    assert row(url, "SELECT app.deposit_required_total_at(%s,'infinity')", source["deposit"]) == (
        10_000,
    )


def test_an_adjustment_waits_for_a_termination_being_saved(migrated_database_url: str) -> None:
    """A voluntary early termination is saved in an open transaction, which holds the Lease's
    Deposit locks; a required-amount increase of the Security Deposit waits for it and is recorded
    after its commit, dated after the termination."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    human, prop, lease, deposit = (
        source["actor"],
        source["property"],
        source["lease"],
        source["deposit"],
    )
    context = approved_test_termination_context(TerminationBasis.VOLUNTARY_EARLY, warning_ids=())
    with psycopg.connect(url) as terminating, ThreadPoolExecutor(max_workers=1) as pool:
        current = terminating.execute(
            "SELECT version FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert current is not None
        terminating.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,"
            "statement_timestamp(),%s,%s,%s,%s)",
            (
                prop,
                uuid4(),
                "b" * 64,
                uuid4(),
                lease,
                current[0],
                source["today"],
                "BR-LEASE-021",
                "Approved synthetic voluntary departure",
                human,
                Jsonb(context.intent()),
            ),
        )
        waiting = pool.submit(adjust, url, human, prop, deposit, 1_000)
        try:
            wait_until_blocked_by(url, terminating)
            assert not waiting.done()
        finally:
            terminating.commit()
        waiting.result(timeout=60)
    assert row(
        url,
        "SELECT lease.status,bool_and(adjustment.occurred_at>lease.terminated_at),count(*) "
        "FROM app.leases lease JOIN app.deposit_required_amount_adjustments adjustment "
        "ON adjustment.deposit_id=%s WHERE lease.id=%s GROUP BY lease.status",
        deposit,
        lease,
    ) == ("TERMINATED", True, 1)


@pytest.mark.parametrize("change", ["receipt", "decrease"])
def test_a_deposit_change_saved_while_a_termination_waits_refuses_it(
    migrated_database_url: str, change: str
) -> None:
    """Review round 1 (security should-fix 1): an unpaid-Initial termination stamped with the
    database's time starts first and, holding the Lease, waits for the Unit. Meanwhile a 40,000
    receipt (the Security Deposit then holds its 50,000 total) or a 40,000 decrease (the total
    then is the 10,000 it holds) is saved and committed, dated after the termination's time. The
    termination is refused (40001) instead of reading the Deposit at its earlier time and keeping
    the Lease's curing money; the Lease stays signed, and a new attempt takes a new time, reads the
    change and finds the ground not met."""
    url = migrated_database_url
    source = initial_rent_paid(url)
    human, prop, deposit = source["actor"], source["property"], source["deposit"]
    paid_by = payment(url, human, deposit, 40_000) if change == "receipt" else None
    with psycopg.connect(url) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.execute("SELECT 1 FROM app.units WHERE id=%s FOR UPDATE", (source["unit"],))
        waiting = pool.submit(unpaid_initial_now, url, source)
        try:
            wait_until_blocked_by(url, holder)
            if paid_by is None:
                adjust(url, human, prop, deposit, 40_000, decrease=True)
            else:
                PostgresDepositService(financial_database_url(), prop, human).record_receipt(
                    receipt_command(deposit, paid_by, 40_000), actor=allocator(human, prop)
                )
            assert not waiting.done()
        finally:
            holder.commit()
        assert waiting.result(timeout=60) == ("40001", CHANGED)
    assert row(url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]) == ("SIGNED",)
    assert row(
        url,
        "SELECT app.deposit_held_value_at(%s,'infinity'),"
        "app.deposit_required_total_at(%s,'infinity')",
        deposit,
        deposit,
    ) == ((50_000, 50_000) if change == "receipt" else (10_000, 10_000))
    assert unpaid_initial_now(url, source) == ("22023", GROUND_NOT_MET)


def test_a_pet_departure_waits_for_a_termination_and_is_refused(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent blocker 1): the Pet departure writer now locks the Lease before
    its Pet Deposit (the termination's order), so it never holds the Deposit while its foreign key
    waits for a terminating Lease (no deadlock). A departure saved beside an uncommitted voluntary
    early termination waits for it and, after its commit, reads the terminated Lease and is
    refused (not found as an eligible Pet Deposit); no departure is written."""
    url = migrated_database_url
    service, who, lease, approval, approved = setup_signed_pet_lease(url)
    deposit, _ = create_pet(service, who, lease, approval, approved)
    business_day = approved + timedelta(days=1)
    context = approved_test_termination_context(TerminationBasis.VOLUNTARY_EARLY, warning_ids=())
    with psycopg.connect(url) as terminating, ThreadPoolExecutor(max_workers=1) as pool:
        current = terminating.execute(
            "SELECT lease.version,unit.property_id FROM app.leases lease "
            "JOIN app.units unit ON unit.id=lease.unit_id WHERE lease.id=%s",
            (lease,),
        ).fetchone()
        assert current is not None
        terminating.execute(
            TERMINATE_NOW,
            (
                current[1],
                uuid4(),
                "f" * 64,
                uuid4(),
                lease,
                current[0],
                business_day,
                "BR-LEASE-021",
                "Approved synthetic voluntary departure",
                service.actor_id,
                Jsonb(context.intent()),
            ),
        )
        waiting = pool.submit(
            service.record_pet_departure,
            RecordPetDepartureCommand(
                uuid4(), uuid4(), deposit, business_day, "Pet permanently left"
            ),
            actor=who,
        )
        try:
            wait_until_blocked_by(url, terminating)
            assert not waiting.done()
        finally:
            terminating.commit()
        with pytest.raises(DepositNotFoundError):
            waiting.result(timeout=60)
    assert row(
        url,
        "SELECT lease.status,(SELECT count(*) FROM app.lease_pet_departures departure "
        "WHERE departure.lease_id=lease.id) FROM app.leases lease WHERE lease.id=%s",
        lease,
    ) == ("TERMINATED", 0)


def test_the_termination_database_time_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the bodies of the two termination functions, the required-amount
    adjustment and the Pet departure writer (owner, privileges, definer flag and settings kept):
    the replay no longer compares the saved time; the Deposit lock comes once, after the version
    and status checks (review round 2), followed by the changed-while-waiting refusal and then the
    context and ground checks; the adjustment is
    dated with clock_timestamp(); the departure locks the Lease before its Pet Deposit. No function
    is added and no trigger, relation, column, privilege or constraint changes; the migration is
    forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270113_170"
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
        return functions, triggers, structure

    with _temporary_migration_database("termination_database_time") as temporary:
        alembic_command.upgrade(config, "20270113_170")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {WITH_CONTEXT, TERMINATE, ADJUST, DEPARTURE}
    for name in (WITH_CONTEXT, TERMINATE, ADJUST, DEPARTURE):
        # Owner, privileges, definer and settings stay; only the body changes.
        assert after_functions[name][1:] == before_functions[name][1:]
    replay = str(after_functions[WITH_CONTEXT][0])
    assert str(before_functions[WITH_CONTEXT][0]).count(SAVED_TIME) == 1
    assert replay.count(SAVED_TIME) == 0
    assert replay.count("v_saved.request_digest IS DISTINCT FROM p_request_digest") == 1
    terminate = str(after_functions[TERMINATE][0])
    assert str(before_functions[TERMINATE][0]).count(DEPOSIT_LOCK) == 0
    assert terminate.count(DEPOSIT_LOCK) == 1
    assert terminate.count(CHANGED.replace("'", "''")) == 1
    assert (
        terminate.index("FROM app.units WHERE id = v_lease.unit_id FOR UPDATE")
        < terminate.index("IF v_lease.version <> p_expected_version")
        < terminate.index("Only a signed Lease may be terminated")
        < terminate.index(DEPOSIT_LOCK)
        < terminate.index(CHANGED.replace("'", "''"))
        < terminate.index("PERFORM app.require_lease_termination_context(")
    )
    adjusted = str(after_functions[ADJUST][0])
    assert "btrim(p_reason),statement_timestamp(),p_actor_id" in str(before_functions[ADJUST][0])
    assert adjusted.count("btrim(p_reason),clock_timestamp(),p_actor_id") == 1
    assert adjusted.count("statement_timestamp()") == 0
    departure = str(after_functions[DEPARTURE][0])
    assert str(before_functions[DEPARTURE][0]).count(LEASE_FIRST) == 0
    assert departure.count(LEASE_FIRST) == 1
    assert departure.index(LEASE_FIRST) < departure.index("FOR UPDATE OF deposit")
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
