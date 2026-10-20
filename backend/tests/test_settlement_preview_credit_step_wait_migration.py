"""The preview lists another Settlement's waiting correction draft that uses a Lease person's
Credit (V1-056 sub-slice 10i-4c).

Owner answer (a) to Q-2026-10-20-146 (BR-SETTLE-002, BR-SETTLE-012, BR-SETTLE-013, BR-CREDIT-008,
DL-032): the Final Settlement preview's pending-draft check also lists a closed Settlement's
waiting correction draft whose plan uses, or whose REFUND releases value into, a Customer Credit
held by a person of another Lease. That other Lease's Settlement waits until the draft is
confirmed, rejected or withdrawn; no amount rule changes, only the order. A Settlement's own
correction draft is not listed for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import (
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
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
    two_signer_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import charge_remaining, one, outstanding
from test_final_settlement_preview_migration import APPROVE, pay
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import setup_reservation_sources
from test_settlement_charge_reduction_migration import invoice_of
from test_settlement_correction_migration import approver
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import (
    command,
    record_refund,
)
from test_settlement_preview_waiting_drafts_migration import (
    SETTLEMENT_DRAFTS,
    STRUCTURE,
    blocked_only_by,
    pending,
    ready_again,
    withdraw,
)
from test_settlement_refund_correction_migration import confirm, correction, record
from test_settlement_refund_return_migration import available

REVISION = "20270117_174"
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
DRAFT_PARTS = (
    "SELECT payload->'plan'->'steps',payload->'plan_overlay'->'credits' "
    "FROM app.financial_drafts WHERE id=%s"
)


def other_lease(
    url: str, monkeypatch: pytest.MonkeyPatch, customer: UUID, credit: UUID
) -> dict[str, Any]:
    """The Customer's second Lease in the shared test Property (a new Unit), built by the leaving
    fixture: terminated, its Final Settlement not recorded. Its own Initial Rent Credit is the
    Customer's only Credit with value other than `credit`."""

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
            "WHERE customer_id=%s AND id<>%s AND app.credit_available_value(id)>0",
            (customer, credit),
        ).fetchall()
    case["credit"] = UUID(str(own_credit))
    return case


def closed(url: str, case: dict[str, Any]) -> bool:
    found = one(
        url,
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        case["settlement"],
    )
    return bool(found[0])


def test_a_waiting_correction_whose_plan_uses_a_credit_holds_the_other_lease(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Q-146 example on the real path. Customer C's Lease A is closed; A's REFUND correction
    draft of 4,000 of its other line waits, and its plan lets C's Credit K (300) pay that line
    first. C's second Lease B is terminated. While the draft waits it is B's only blocking issue
    (its identity shown to an approver and to a final_settlements.prepare holder), B's Settlement
    draft is not recorded (55000, nothing written) and K keeps its 300; A's own preview does not
    list its own draft, and the preview of a Lease none of whose people holds K is not held.
    After the withdrawal B is ready and closes with a plan in which K pays 300 of B's line (B may
    apply all of K once A's draft is withdrawn). A's draft is recorded before B exists: B's own
    Initial Rent Credit is also C's, and DL-032 would make A's plan apply it too (test run T1)."""
    url = migrated_database_url
    first = {**closed_case(url), "url": url}
    credit, line = first["new_credit"], first["other_line"]
    assert available(url, credit) == 300

    def refund_draft() -> UUID:
        return record_refund(
            first,
            command(
                first,
                line,
                4_000,
                SettlementCreditStep(credit, LINE, line, 300),
                SettlementDepositStep(SECURITY, first["security"], LINE, line, 7_800),
                settlement_refund(first, "security", 2_200),
                settlement_refund(first, "pet", 2_100),
            ),
        )

    draft = refund_draft()
    second = other_lease(url, monkeypatch, first["customer"], credit)
    steps, _ = one(url, DRAFT_PARTS, draft)
    assert [step["customer_credit_id"] for step in steps if step["kind"] == "CUSTOMER_CREDIT"] == [
        str(credit)
    ]
    issue: dict[str, object] = {
        "code": "PENDING_DRAFT",
        "draft_id": str(draft),
        "kind": "SETTLEMENT_CORRECTION",
        "variant": "REFUND",
    }
    blocked_only_by(second, issue)
    assert pending(second) == [issue]
    assert pending(first, APPROVE) == []
    stranger = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    assert pending(stranger) == []
    assert outstanding(url, second["other_line"]) == 12_500
    with_k = (
        SettlementCreditStep(second["credit"], LINE, second["other_line"], 400),
        SettlementCreditStep(credit, LINE, second["other_line"], 300),
        SettlementDepositStep(PET_FIRST, second["pet"], LINE, second["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, second["security"], LINE, second["other_line"], 10_000),
        SettlementDepositStep(PET_REST, second["pet"], LINE, second["other_line"], 1_800),
        settlement_refund(second, "pet", 5_700),
    )
    before = one(url, SETTLEMENT_DRAFTS)
    assert refusal(record_settlement, second, with_k, pet_remainder=STAFF) == ("55000", BLOCKED)
    assert (one(url, SETTLEMENT_DRAFTS), available(url, credit)) == (before, 300)

    withdraw(first, draft, "final_settlements.prepare")
    ready_again(second)
    confirm_settlement(second, record_settlement(second, with_k, pet_remainder=STAFF))
    assert closed(url, second)
    assert available(url, credit) == 0
    assert outstanding(url, second["other_line"]) == 0


def test_a_waiting_refund_that_releases_value_into_a_credit_holds_the_other_lease(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The release part of the answer. At A's closure the second Signer S's Credit K pays 400 of
    S's 1,000 line and S pays the 600 left after closure. A REFUND correction draft of 800 of
    that line releases the 600 Payment value (keyed by its allocation, a new Credit only at the
    confirm) and 200 of K's application back into K; its plan has no CUSTOMER_CREDIT step. S's
    own Lease B is terminated and B's Settlement draft is recorded before the correction draft
    (review round 1, independent should-fix 1): while the correction draft waits it is B's only
    blocking issue and the 8e-3 confirm of B's draft is refused (55000; it stays pending and
    nothing is written); once the correction is confirmed, B's early draft is withdrawn (staff
    record it again, as the 10h-4a test does) and B closes."""
    url = migrated_database_url
    first = two_signer_case(url, overdue_rent=True)
    prop, human, pet, charge = first["prop"], first["human"], first["pet"], first["charge"]
    signer, credit, line = first["co_signer"], first["credit"], first["signer_line"]
    person = approver(url)
    on_charge = charge_remaining(url, charge)
    confirm_settlement(
        first,
        record_settlement(
            first,
            (
                SettlementCreditStep(credit, LINE, line, 400),
                SettlementDepositStep(
                    PET_REST, pet, SettlementTargetKind.LATE_PAYMENT_CHARGE, charge, on_charge
                ),
                SettlementDepositStep(PET_REST, pet, LINE, first["rent_line"], 20_000 - on_charge),
            ),
            pet_remainder=STAFF,
        ),
    )
    invoice = invoice_of(url, line)
    assert outstanding(url, line) == 600
    pay(url, prop, human, signer, invoice, line, 600)
    second = other_lease(url, monkeypatch, signer, credit)
    early = record_settlement(second, normal_plan(second), pet_remainder=STAFF)
    draft = record(first, correction(first, invoice, line, 800))
    steps, released = one(url, DRAFT_PARTS, draft)
    assert [step for step in steps if step["kind"] == "CUSTOMER_CREDIT"] == []
    assert released[str(credit)]["add_usd_cents"] == 200
    issue: dict[str, object] = {
        "code": "PENDING_DRAFT",
        "draft_id": str(draft),
        "kind": "SETTLEMENT_CORRECTION",
        "variant": "REFUND",
    }
    blocked_only_by(second, issue)
    owed = outstanding(url, second["other_line"])
    assert refusal(confirm_settlement, second, early) == ("55000", BLOCKED)
    assert (settlement_state(url, early), closed(url, second)) == ("PENDING", False)
    assert outstanding(url, second["other_line"]) == owed
    confirm(first, person, draft)
    assert (available(url, credit), outstanding(url, line)) == (0, 0)
    withdraw(second, early["draft_id"], "final_settlements.prepare")
    ready_again(second)
    confirm_settlement(second, record_settlement(second, normal_plan(second), pet_remainder=STAFF))
    assert closed(url, second)


def test_the_credit_step_wait_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the body of app.final_settlement_preview (owner, privileges,
    definer flag and settings kept), adds the correction branch once, adds no function, changes
    no trigger, relation, column, privilege or constraint, and is forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270116_173"
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
            structure = {
                ":".join(str(value) for value in row)
                for query in STRUCTURE
                for row in connection.execute(query).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_preview_credit_step_wait") as temporary:
        alembic_command.upgrade(config, "20270116_173")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PREVIEW}
    assert after_functions[PREVIEW][1:] == before_functions[PREVIEW][1:]
    preview = str(after_functions[PREVIEW][0])
    step_branch = "WHERE step->>'kind'='CUSTOMER_CREDIT' AND credit.customer_id=ANY(v_people)"
    assert preview.count(step_branch) == 1
    assert preview.count("JOIN app.customer_credits credit ON credit.id::text=item.key") == 1
    assert str(before_functions[PREVIEW][0]).count("item.key") == 0
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
