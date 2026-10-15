"""Post-settlement correction: a returned Credit's count takes the corrections of every Final
Settlement that use it (sub-slice 10e-3d-2d-1).

Owner answer (a) to Q-2026-10-13-100 point 2: a correction on another Lease of the same Customer
that uses the returned Credit counts too. A Customer Credit belongs to the Customer, so a
correction's DL-032 step on the Customer's other Lease applies it to the open debt there. The
walk now takes, for a Credit, the corrections of every Final Settlement whose records use it, in
one time order; a Deposit belongs to one Lease, so its walk does not change. Until sub-slice
10e-3d-2d-2 builds the undo on the other Lease with a companion correction of its Settlement
(owner answer (a) to Q-2026-10-13-103 point 3), a reversal of a return whose money such a
correction used is refused first, with nothing written.
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
from psycopg.types.json import Jsonb

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, leaving_case, normal_plan
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import setup_reservation_sources
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    COUNTS,
    NOTHING_LEFT,
    confirm_held,
    credit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    return_command,
)
from test_settlement_return_reversal_migration import (
    app_catalog,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_payment_migration import closed_case
from test_settlement_returned_value_left_migration import CHANGED, counted

REVISION = "20261211_137"
WALK = "app.settlement_returned_value_walk(uuid,text,uuid,uuid)"
PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
STATE = "SELECT app.settlement_return_reversal_source_state(%s,%s)"
OTHER_SETTLEMENT = (
    "A correction of another Lease's Final Settlement used this return's money; reversing it "
    "waits for sub-slice 10e-3d-2d-2"
)


def second_lease(url: str, monkeypatch: pytest.MonkeyPatch, customer: UUID) -> dict[str, Any]:
    """The Customer's second Lease in the shared test Property (a new Unit), built by the same
    leaving fixture and closed by the same 8c normal-end plan as the first: its own Initial Rent
    Credit (400) pays the other damage line, the Deposits pay the damage lines and the Pet
    Deposit's rest (5,400) is refunded."""

    def same_customer(connection: psycopg.Connection[tuple[object, ...]]) -> tuple[Any, ...]:
        actor_id, prop, unit, _ = setup_reservation_sources(connection)
        return actor_id, prop, unit, customer

    with monkeypatch.context() as patched:
        patched.setattr(initial_fixture, "setup_reservation_sources", same_customer)
        case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    assert case["customer"] == customer
    # The fixture names the Customer's first Credit; this Lease's own is the only one with value.
    with psycopg.connect(url) as connection:
        [(own_credit,)] = connection.execute(
            "SELECT id FROM app.customer_credits "
            "WHERE customer_id=%s AND app.credit_available_value(id)>0",
            (customer,),
        ).fetchall()
    case["credit"] = UUID(str(own_credit))
    confirm_settlement(case, record_settlement(case, normal_plan(case), pet_remainder=STAFF))
    case["person"] = correction_approver(url)
    return case


def two_lease_case(
    url: str, monkeypatch: pytest.MonkeyPatch, returned: int = 300, credit_paid: int = 300
) -> dict[str, Any]:
    """The owner's Q-2026-10-13-103 point 3 example on the real path. The first Lease A closes; a
    REFUND correction of its Initial Rent line refunds 2,000 of released Payment value from a new
    Credit to the Customer; the Customer's second Lease B closes. A return-only correction X1 of
    A brings back 300 of that Refund into the Credit. After closure B issues an unpaid 1,500
    charge to the same Customer; a REFUND_RETURN of B's Settlement Pet Deposit Refund (5,400,
    with a new Refund) lets the Credit pay 300 of the charge first (DL-032: each Customer's Credit
    pays that Customer's open debt first while a Deposit holds money), the Pet Deposit 1,200, and
    refunds 4,200. With other amounts X1 brings back `returned` and the Credit pays `credit_paid`
    of the charge; when that is the whole charge the Pet Deposit's 5,400 is all refunded."""
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    assert available(url, credit) == 0
    second = second_lease(url, monkeypatch, first["customer"])
    earlier = return_only(first, refund, returned)
    assert (available(url, credit), credit_left(url, earlier, credit)) == (returned, returned)
    _, charge_line = unpaid_charge(url, second, second["person"])
    pet, rest = second["pet"], 1_500 - credit_paid
    steps: list[Any] = [SettlementCreditStep(credit, LINE, charge_line, credit_paid)]
    if rest:
        steps.append(SettlementDepositStep(PET_REST, pet, LINE, charge_line, rest))
    steps.append(settlement_refund(second, "pet", 5_400 - rest))
    result = confirm(
        second,
        record(
            second,
            return_command(
                second,
                pet_refund(second),
                5_400,
                *steps,
                pet_remainder=STAFF if rest else None,
            ),
        ),
    )
    [applied] = result["credit_applications"]
    assert (applied["customer_credit_id"], applied["amount_usd_cents"]) == (
        str(credit),
        credit_paid,
    )
    assert (available(url, credit), outstanding(url, charge_line), held(url, pet)) == (
        returned - credit_paid,
        0,
        0,
    )
    return {
        "first": first,
        "second": second,
        "refund": refund,
        "credit": credit,
        "earlier": earlier,
        "taker": UUID(str(result["settlement_correction"]["id"])),
    }


def test_another_lease_s_correction_counts_against_a_return_and_its_reversal_waits(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner answer (a) to Q-2026-10-13-100 point 2: the second Lease's correction used X1's 300,
    so X1 has nothing left, read from either Settlement (before this sub-slice it kept 300 while
    the Credit held nothing); a held-value Refund naming X1 is refused; X1's reversal is refused
    with the new message (its undo on the other Lease is sub-slice 10e-3d-2d-2) and writes
    nothing; the Credit, the charge and the Refund's net stay; the ledger reconciles."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch)
    first, second, credit, earlier = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
    )
    expected = {str(earlier): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    assert credit_left(url, earlier, credit) == 0
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as nothing_left:
        record_held(first, held_command(first, earlier))
    assert cause(nothing_left) == ("55000", NOTHING_LEFT)
    with pytest.raises(FinalSettlementConflictError) as waits:
        record_reversal(first, reversal_command(first, earlier))
    assert cause(waits) == ("55000", OTHER_SETTLEMENT)
    assert one(url, COUNTS) == unchanged
    assert (available(url, credit), net(url, found["refund"])) == (0, 1_700)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_later_return_s_money_is_not_paid_out_for_an_earlier_return(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 (the harm of Q-2026-10-13-100 point 2 (b)): X1 brings back
    1,700; the second Lease's correction lets the Credit pay the whole 1,500 charge there first
    and refunds the Pet Deposit's 5,400 again. A later return-only correction X3 brings back the
    Refund's last 300, so the Credit holds 500: X1 has 200 left and X3 300, read from either
    Settlement. X1's reversal is refused (the other Lease's correction used 1,500 of its money)
    with nothing written; a held-value Refund naming X1 refunds exactly 200 (before this
    sub-slice X1 kept 1,700 left and it would have refunded 500, X3's 300 included), and one
    naming X3 then refunds X3's 300. The Credit ends empty and the ledger reconciles."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch, returned=1_700, credit_paid=1_500)
    first, second, refund, credit, earlier = (
        found["first"],
        found["second"],
        found["refund"],
        found["credit"],
        found["earlier"],
    )
    later = return_only(first, refund, 300)
    assert (available(url, credit), net(url, refund)) == (500, 0)
    expected = {str(earlier): (1_700, 1_500, 1_500, 200), str(later): (300, 0, 0, 300)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as waits:
        record_reversal(first, reversal_command(first, earlier))
    assert cause(waits) == ("55000", OTHER_SETTLEMENT)
    assert one(url, COUNTS) == unchanged
    customer = str(first["customer"])
    [paid] = confirm_held(first, record_held(first, held_command(first, earlier)))["refunds"]
    assert (
        paid["source_customer_credit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
    ) == (str(credit), customer, 200)
    assert (available(url, credit), credit_left(url, earlier, credit)) == (300, 0)
    assert credit_left(url, later, credit) == 300
    [paid_later] = confirm_held(first, record_held(first, held_command(first, later)))["refunds"]
    assert (
        paid_later["source_customer_credit_id"],
        paid_later["recipient_customer_id"],
        paid_later["amount_usd_cents"],
    ) == (str(credit), customer, 300)
    assert (available(url, credit), credit_left(url, later, credit)) == (0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_take_by_another_settlement_s_correction_is_one_open_part_refused_first(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X1's source names the second Lease's correction as one open part (kind OTHER_SETTLEMENT,
    its whole 300), none of its records for undoing; the refusal function refuses that source,
    and refuses an OTHER_SETTLEMENT part first when another open part (a changed payment) is in
    the same source, and as an own use's open part on the walk path. A Deposit belongs to one
    Lease: the first Settlement's walk of the second
    Lease's Pet Deposit is empty, the second's counts only its own return (5,400 returned and
    used, nothing swept)."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch)
    first, second, earlier, taker = (
        found["first"],
        found["second"],
        found["earlier"],
        found["taker"],
    )
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept"] == [] and source["swept_undone_usd_cents"] == 0
    assert source["swept_usd_cents"] == 300 and source["recoveries"] == []
    assert [
        (item["kind"], item["record_kind"], item["record_id"], item["part_usd_cents"])
        for item in source["swept_open"]
    ] == [("OTHER_SETTLEMENT", "OTHER_SETTLEMENT", str(taker), 300)]
    [part] = source["swept_open"]
    assert part["settlement_correction_id"] == str(taker)
    changed = {
        "settlement_correction_id": str(uuid4()),
        "kind": "CHANGED_APPLICATION",
        "record_kind": "CREDIT_APPLICATION",
        "record_id": str(uuid4()),
        "part_usd_cents": 100,
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    for built, message in (
        (source, OTHER_SETTLEMENT),
        (
            {
                **source,
                "swept_usd_cents": 400,
                "swept_open": [changed, part],
            },
            OTHER_SETTLEMENT,
        ),
        (
            {
                **source,
                "swept_usd_cents": 100,
                "swept_open": [changed],
            },
            CHANGED,
        ),
        # Independent review round 1 (N1): an own use's open part on the walk path too.
        (
            {
                **source,
                "swept_usd_cents": 0,
                "swept_open": [],
                "own_parts": [],
                "own_open": [part],
            },
            OTHER_SETTLEMENT,
        ),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), built
    assert counted(url, first["settlement"], "DEPOSIT", second["pet"]) == {}
    [own] = counted(url, second["settlement"], "DEPOSIT", second["pet"]).values()
    assert own == (5_400, 5_400, 0, 0)


def test_the_returned_value_count_of_other_settlements_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 137 changes only the walk, the placed function and the refusal function (each
    body exactly the old one with the module's replacements; privileges, owner, definer and
    settings kept), adds no function, constraint or trigger, no role may call the three, and it
    is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (WALK, PLACED, ASSERT):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261210_136"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_returned_value_other_settlements") as temporary:
        alembic_command.upgrade(config, "20261210_136")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
    patched = dict(revision.module.PATCHES)
    assert set(patched) == {WALK, PLACED, ASSERT}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(patched)
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
