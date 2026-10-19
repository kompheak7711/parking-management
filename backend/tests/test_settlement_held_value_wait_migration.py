"""A waiting held-value Refund draft in the preview, and the 6b draft at READ COMMITTED only
(V1-056 sub-slice 10h-4a).

Owner answer 2 of 2026-10-20 to the 10h-3 report (BR-SETTLE-002, BR-SETTLE-013, BR-CREDIT-008,
DL-032): the Final Settlement preview also lists another Settlement's waiting HELD_VALUE_REFUND
correction draft whose Credit a person of the Lease holds, so that Lease neither records nor
confirms its Settlement while the draft would pay the same Credit's money out; a Settlement's own
held-value draft is not listed for it. Owner answer 1 of 2026-10-20 to the 10h-2 report
(BR-DEP-019, BR-AUTH-010): the 6b forfeiture reversal draft is recorded and confirmed only at READ
COMMITTED, so an older snapshot cannot record or confirm one after a closure it does not see.
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

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.refund import CreateUsdRefundCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor as refund_actor
from test_final_settlement_confirm_migration import BLOCKED, this_month
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import state as settlement_state
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    leaving_case,
    normal_plan,
    refusal,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one, outstanding
from test_final_settlement_preview_migration import APPROVE
from test_lease_deposit_reversal_draft_migration import (
    decisions,
    forfeited_security,
    forfeitures,
    reversal,
    reversals,
    staff,
)
from test_lease_deposit_reversal_draft_migration import held as held_value
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import service as refunds
from test_reservation_migration import setup_reservation_sources
from test_settlement_forfeiture_reversal_after_closure_migration import isolation_refusal
from test_settlement_held_value_refund_migration import (
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_preview_waiting_drafts_migration import (
    SETTLEMENT_DRAFTS,
    STRUCTURE,
    blocked_only_by,
    pending,
    ready_again,
    withdraw,
)
from test_settlement_refund_return_migration import available, refunded_case
from test_termination_deposit_migration import setup_deposits

REVISION = "20270112_169"
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"
SIX_B_READ_COMMITTED = (
    "A Lease Deposit forfeiture reversal draft is recorded and confirmed at READ COMMITTED"
)
RECORD_SIX_B = (
    "SELECT app.record_lease_deposit_reversal_draft(%s,%s,%s,%s,%s,%s,%s,'deposits.correct')"
)
CONFIRM_SIX_B = "SELECT app.confirm_lease_deposit_reversal_draft(%s,%s,%s,%s,'financial.approve')"
STRICTER = (psycopg.IsolationLevel.REPEATABLE_READ, psycopg.IsolationLevel.SERIALIZABLE)
SIX_B_DRAFTS = (
    "SELECT count(*) FROM app.financial_drafts WHERE kind='DEPOSIT_FORFEITURE' "
    "AND payload->>'variant'='LEASE_FORFEITURE_REVERSAL' AND payload->>'disposition_id'=%s"
)


def open_second_lease(url: str, monkeypatch: pytest.MonkeyPatch, customer: UUID) -> dict[str, Any]:
    """The Customer's second Lease in the shared test Property (a new Unit), built by the leaving
    fixture: terminated, its Final Settlement not recorded (as `second_lease` of the other
    settlements module, without its closure). Its own Initial Rent Credit (400) is the
    Customer's only Credit with value at this point."""

    def same_customer(connection: psycopg.Connection[tuple[object, ...]]) -> tuple[Any, ...]:
        actor_id, prop, unit, _ = setup_reservation_sources(connection)
        return actor_id, prop, unit, customer

    with monkeypatch.context() as patched:
        patched.setattr(initial_fixture, "setup_reservation_sources", same_customer)
        case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    assert case["customer"] == customer
    with psycopg.connect(url) as connection:
        [(own_credit,)] = connection.execute(
            "SELECT id FROM app.customer_credits "
            "WHERE customer_id=%s AND app.credit_available_value(id)>0",
            (customer,),
        ).fetchall()
    case["credit"] = UUID(str(own_credit))
    return case


def test_a_waiting_held_value_refund_holds_the_open_lease_of_its_credit_s_customer(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The money example of the 10h-4 pre-code design on the real path. Customer C's Lease A is
    closed; a REFUND correction refunded 2,000 of C's Credit K and a return-only correction X1
    brought the 2,000 back, so K holds 2,000. A HELD_VALUE_REFUND draft H naming X1 waits (C
    owes nothing on A, so H would refund all 2,000). C's second Lease B is terminated; its
    Settlement could let K pay 2,000 of B's other damage line first. While H waits it is B's only
    blocking issue (shown to a final_settlements.prepare holder and to an approver), B's
    Settlement draft that applies K is not recorded (55000, nothing written) and K keeps its
    2,000; A's own preview does not list H, nor does the preview of a Lease none of whose people
    holds K. After H is withdrawn B is ready and records the Settlement draft that applies K; a
    new held-value draft H2 then refuses that draft's confirm (55000; it stays pending, K keeps
    2,000 and B's line its 12,500). Once H2 is confirmed (2,000 refunded to C, K holds 0) the
    early draft is withdrawn, B's preview is ready and B closes with its own Credit and
    Deposits."""
    url = migrated_database_url
    first = refunded_case(url)
    # open_second_lease expects the Customer's only Credit with value to be the second Lease's
    # own, so the first case's other 300 of Credit (no return in it) is refunded first.
    create_usd_refund(
        refunds(),
        first["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", first["new_credit"], 300, "Customer asked"),
        actor=refund_actor(first["human"], first["prop"], "refunds.create"),
    )
    second = open_second_lease(url, monkeypatch, first["customer"])
    credit = first["refund_credit"]
    earlier = return_only(first, first["refund"], 2_000)
    assert available(url, credit) == 2_000
    draft = record_held(first, held_command(first, earlier))
    issue: dict[str, object] = {
        "code": "PENDING_DRAFT",
        "draft_id": str(draft),
        "kind": "SETTLEMENT_CORRECTION",
        "variant": "HELD_VALUE_REFUND",
    }
    blocked_only_by(second, issue)
    assert pending(second) == [issue]
    assert pending(first, APPROVE) == []
    owed = outstanding(url, second["other_line"])
    assert owed == 12_500
    with_k = (
        SettlementCreditStep(second["credit"], LINE, second["other_line"], 400),
        SettlementCreditStep(credit, LINE, second["other_line"], 2_000),
        SettlementDepositStep(PET_FIRST, second["pet"], LINE, second["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, second["security"], LINE, second["other_line"], 10_000),
        SettlementDepositStep(PET_REST, second["pet"], LINE, second["other_line"], 100),
        settlement_refund(second, "pet", 7_400),
    )
    before = one(url, SETTLEMENT_DRAFTS)
    assert refusal(record_settlement, second, with_k, pet_remainder=STAFF) == ("55000", BLOCKED)
    assert (one(url, SETTLEMENT_DRAFTS), available(url, credit)) == (before, 2_000)
    assert outstanding(url, second["other_line"]) == owed
    # Review round 1 (independent should-fix 2): a Lease none of whose people holds K is not held.
    stranger = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    assert pending(stranger) == []
    # Review round 1 (security note 2, independent note 4): a Settlement draft of B recorded
    # before the held-value draft is refused at its confirm and stays pending.
    withdraw(first, draft, "final_settlements.prepare")
    ready_again(second)
    early = record_settlement(second, with_k, pet_remainder=STAFF)
    draft = record_held(first, held_command(first, earlier))
    issue = {**issue, "draft_id": str(draft)}
    blocked_only_by(second, issue)
    assert refusal(confirm_settlement, second, early) == ("55000", BLOCKED)
    assert settlement_state(url, early) == "PENDING"
    assert (available(url, credit), outstanding(url, second["other_line"])) == (2_000, owed)
    result = confirm_held(first, draft)
    [paid] = result["refunds"]
    assert (
        paid["source_customer_credit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
    ) == (str(credit), str(first["customer"]), 2_000)
    assert available(url, credit) == 0
    # The early draft applied K, which now holds nothing: it is withdrawn and B records again.
    withdraw(second, early["draft_id"], "final_settlements.prepare")
    ready_again(second)
    confirm_settlement(second, record_settlement(second, normal_plan(second), pet_remainder=STAFF))
    assert one(
        url,
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        second["settlement"],
    ) == (True,)
    assert outstanding(url, second["other_line"]) == 0


def test_a_six_b_draft_is_recorded_and_confirmed_only_at_read_committed(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to the 10h-2 report: on a Lease with no Final Settlement, a 6b reversal
    draft of the forfeited Security Deposit is refused at REPEATABLE READ and at SERIALIZABLE
    (55000) with no draft written, while an exact repeat of a recorded draft still replays at
    REPEATABLE READ (the replay comes before any current-state check). The confirm of the waiting
    draft is refused at both levels (55000): the draft stays pending and nothing is written. At
    READ COMMITTED the approver's confirm reverses the forfeiture and the Deposit holds its money
    again."""
    url = migrated_database_url
    human, prop, security, _, disposition, amount = forfeited_security(url)
    for level in STRICTER:
        assert isolation_refusal(
            url,
            level,
            RECORD_SIX_B,
            (prop, human, uuid4(), disposition, uuid4(), "Wrong ground recorded", "CASE-6B"),
        ) == ("55000", SIX_B_READ_COMMITTED), level
    assert one(url, SIX_B_DRAFTS, str(disposition)) == (0,)
    command = reversal(disposition)
    recorded = forfeitures().record_reversal(
        prop, command, actor=staff(human, prop, "deposits.correct")
    )
    draft = UUID(str(recorded["draft_id"]))
    with psycopg.connect(url) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        replayed = connection.execute(
            RECORD_SIX_B,
            (
                prop,
                human,
                draft,
                disposition,
                command.reversal_id,
                command.reason,
                command.evidence_reference,
            ),
        ).fetchone()
        connection.rollback()
    assert replayed is not None and replayed[0]["draft_id"] == str(draft)
    assert one(url, SIX_B_DRAFTS, str(disposition)) == (1,)
    second = setup_deposits(url)[0]
    for level in STRICTER:
        assert isolation_refusal(url, level, CONFIRM_SIX_B, (prop, second, disposition, draft)) == (
            "55000",
            SIX_B_READ_COMMITTED,
        ), level
    assert (decisions(url, draft), reversals(url, disposition), held_value(url, security)) == (
        0,
        [],
        0,
    )
    forfeitures().confirm_reversal(
        prop, disposition, draft, actor=staff(second, prop, "financial.approve")
    )
    assert decisions(url, draft) == 1
    assert [row[0] for row in reversals(url, disposition)] == [command.reversal_id]
    assert held_value(url, security) == amount


def test_the_held_value_wait_and_6b_isolation_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the bodies of app.final_settlement_preview and the 6b source
    (owner, privileges, definer flag and settings kept), adds the held-value branch and the
    isolation check once each, adds no function, changes no trigger, relation, column, privilege
    or constraint, and is forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270111_168"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text "
                    "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
            # Relations and their privileges, constraints, and table columns (the 10h-3 queries).
            structure = {
                ":".join(str(value) for value in row)
                for query in STRUCTURE
                for row in connection.execute(query).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_held_value_wait") as temporary:
        alembic_command.upgrade(config, "20270111_168")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PREVIEW, SOURCE}
    for name in (PREVIEW, SOURCE):
        # Owner, privileges, definer and settings stay; only the body changes.
        assert after_functions[name][1:] == before_functions[name][1:], name
    preview, source = str(after_functions[PREVIEW][0]), str(after_functions[SOURCE][0])
    assert preview.count("draft.payload->>'variant'='HELD_VALUE_REFUND'") == 1
    assert str(before_functions[PREVIEW][0]).count("HELD_VALUE_REFUND") == 0
    assert source.count(SIX_B_READ_COMMITTED) == 1
    assert source.index(SIX_B_READ_COMMITTED) < source.index("FROM app.deposit_dispositions")
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
