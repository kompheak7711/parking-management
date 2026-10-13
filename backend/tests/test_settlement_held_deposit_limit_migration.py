"""The stricter Deposit count of HELD_VALUE_REFUND (V1-056 sub-slice 10c-2b-4).

Owner answer to Q-2026-10-09-64 (an approved tightening): a held-value correction that names an
earlier return-only correction uses, in each Deposit, at most the value that correction left there,
the Lease debt it pays and the Refund together; a Deposit it returned nothing to gives it nothing.
Owner answer 1 to Q-2026-10-09-65: it must use some of that value and may leave the rest held for a
later correction that names the same earlier correction; BR-SETTLE-008 and the DL-032 order hold
for the money it uses. Other held money stays held until staff prepare a correction that names the
earlier correction which returned it (BR-SETTLE-013, DL-032).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.refund import CreateUsdRefundCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_FIRST, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import service as refunds
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause, state
from test_settlement_held_value_refund_migration import (
    COUNTS,
    EVERY_BALANCE,
    NOTHING_LEFT,
    audit,
    confirm_held,
    deposit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    available,
    confirm,
    record,
    refunded_case,
    return_command,
)

BEYOND_LEFT = (
    "A held-value correction uses at most what its earlier correction left in each Deposit"
)
OPEN_DEBT = "No Deposit Refund while the Lease still has open debt that the Deposit could pay"
SECURITY_FIRST = (
    "The remaining Pet Deposit pays only debt still open after the Security Deposit has been used"
)
PLAN_RESULT = "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)"
CHANGED = {
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)": "PLAN_RESULT_REPLACEMENTS",
    "app.record_settlement_held_value_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)": (
        "RECORD_REPLACEMENTS"
    ),
    "app.post_settlement_correction_plan(uuid,uuid,uuid)": "STEP_REPLACEMENTS",
    "app.confirm_settlement_held_value_refund(uuid,uuid,uuid,text)": "CONFIRM_REPLACEMENTS",
}


def test_a_deposit_correction_uses_at_most_what_its_earlier_correction_left(
    migrated_database_url: str,
) -> None:
    """Two return-only corrections bring back 2,000 and 1,000 of the Settlement's Pet Deposit
    Refund, so the Pet Deposit holds 3,000; the Customer owes a 1,500 charge. Linked to the first,
    with the Customer's Credit (300) first and the remaining Pet Deposit paying 1,200 of the charge:
    a Refund of 900 (debt and Refund together 2,100) is refused and the old full plan (a Refund of
    1,800, every held cent) is refused. Owner answer 1 to Q-2026-10-09-65 ("at most"): a correction
    that uses none of the value is refused with the every-balance message, and one that leaves
    value held still cannot refund while the charge stays open (BR-SETTLE-008); none of them writes
    anything. A Refund of 500 (1,700 used) is confirmed and leaves 300 of the first's value held; a
    second correction naming the first refunds those 300, the first then has nothing left and is
    refused, and a correction linked to the second refunds its 1,000."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, customer = case["pet"], case["customer"]
    first = return_only(case, pet_refund(case), 2_000)
    second = return_only(case, pet_refund(case), 1_000)
    assert (held(url, pet), deposit_left(url, first, pet), deposit_left(url, second, pet)) == (
        3_000,
        2_000,
        1_000,
    )
    _, charge_line = unpaid_charge(url, case, case["person"])
    credit_first = SettlementCreditStep(case["new_credit"], LINE, charge_line, 300)

    def plan(refunded: int) -> Any:
        return held_command(
            case,
            first,
            credit_first,
            SettlementDepositStep(PET_REST, pet, LINE, charge_line, 1_200),
            settlement_refund(case, "pet", refunded),
            pet_remainder=STAFF,
        )

    before = one(url, COUNTS)
    for command, message in (
        (plan(900), BEYOND_LEFT),
        (plan(1_800), BEYOND_LEFT),
        (held_command(case, first), EVERY_BALANCE),
        (held_command(case, first, credit_first, settlement_refund(case, "pet", 500)), OPEN_DEBT),
    ):
        with pytest.raises(FinalSettlementConflictError) as refused:
            record_held(case, command)
        assert cause(refused) == ("55000", message), message
    assert (one(url, COUNTS), held(url, pet), outstanding(url, charge_line)) == (
        before,
        3_000,
        1_500,
    )
    result = confirm_held(case, record_held(case, plan(500)))
    [paid] = result["refunds"]
    assert (paid["source_deposit_id"], paid["recipient_customer_id"], paid["amount_usd_cents"]) == (
        str(pet),
        str(customer),
        500,
    )
    _, confirmed = audit(url, result["settlement_correction"]["id"])
    assert confirmed["settled_deposits"] == [
        {"deposit_id": str(pet), "applied_usd_cents": 1_200, "refunded_usd_cents": 500}
    ]
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        deposit_left(url, first, pet),
        deposit_left(url, second, pet),
    ) == (1_300, 0, 300, 1_000)
    [again] = confirm_held(
        case, record_held(case, held_command(case, first, settlement_refund(case, "pet", 300)))
    )["refunds"]
    assert (again["source_deposit_id"], again["amount_usd_cents"]) == (str(pet), 300)
    assert (held(url, pet), deposit_left(url, first, pet)) == (1_000, 0)
    with pytest.raises(FinalSettlementConflictError) as gone:
        record_held(case, held_command(case, first, settlement_refund(case, "pet", 1_000)))
    assert cause(gone) == ("55000", NOTHING_LEFT)
    [rest] = confirm_held(
        case, record_held(case, held_command(case, second, settlement_refund(case, "pet", 1_000)))
    )["refunds"]
    assert (rest["source_deposit_id"], rest["amount_usd_cents"]) == (str(pet), 1_000)
    assert (held(url, pet), deposit_left(url, second, pet)) == (0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_credit_correction_leaves_held_deposit_money_to_the_correction_that_returned_it(
    migrated_database_url: str,
) -> None:
    """The Pet Deposit holds 2,000 that a return-only correction Ed brought back; a return-only
    correction Ec brings back 1,000 of a correction's Credit Refund; the Customer owes a 1,500
    charge. Linked to Ec, the returned Credit and the Customer's other Credit (300) pay 1,300 of the
    charge first; a Pet Deposit step for the rest is refused (Ec returned no Deposit money) and
    writes nothing. Without it the correction is confirmed with no Refund: the charge keeps 200
    open while the Pet Deposit keeps its 2,000. A correction linked to Ed then lets the Pet Deposit
    pay those 200 and refunds the other 1,800."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer, pet = (
        case["refund"],
        case["refund_credit"],
        case["customer"],
        case["pet"],
    )
    deposit_return = return_only(case, pet_refund(case), 2_000)
    credit_return = return_only(case, refund, 1_000)
    _, charge_line = unpaid_charge(url, case, case["person"])
    credit_steps = (
        SettlementCreditStep(credit, LINE, charge_line, 1_000),
        SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
    )
    pet_step = SettlementDepositStep(PET_REST, pet, LINE, charge_line, 200)
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_held(
            case, held_command(case, credit_return, *credit_steps, pet_step, pet_remainder=STAFF)
        )
    assert cause(refused) == ("55000", BEYOND_LEFT)
    assert (one(url, COUNTS), held(url, pet), available(url, credit)) == (before, 2_000, 1_000)
    result = confirm_held(case, record_held(case, held_command(case, credit_return, *credit_steps)))
    assert result["refunds"] == []
    _, confirmed = audit(url, result["settlement_correction"]["id"])
    assert confirmed["settled_deposits"] == []
    assert (held(url, pet), outstanding(url, charge_line), available(url, credit)) == (
        2_000,
        200,
        0,
    )
    paid_debt = confirm_held(
        case,
        record_held(
            case,
            held_command(
                case,
                deposit_return,
                pet_step,
                settlement_refund(case, "pet", 1_800),
                pet_remainder=STAFF,
            ),
        ),
    )
    [paid] = paid_debt["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 1_800)
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        deposit_left(url, deposit_return, pet),
    ) == (0, 0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_correction_that_names_no_earlier_correction_still_settles_held_money(
    migrated_database_url: str,
) -> None:
    """A returned-Refund correction with a new Refund names no earlier correction and, by
    BR-SETTLE-008, applies or refunds every held DL-032 Deposit balance. After a return-only
    correction Ed brought back 2,000 to the Pet Deposit, the return of 500 of a correction's Credit
    Refund with a new Refund also refunds the Pet Deposit's 2,000. Sub-slice 10e-3d (owner answer
    (a) to Q-2026-10-12-97) ends the known limit this test showed: that use counts against Ed, so
    Ed has nothing left (it showed 2,000 before) and naming Ed is refused and writes nothing. When
    a later return-only correction E3 brings back 500, naming Ed is still refused (before, it could
    take E3's 500), a correction naming E3 refunds the 500, and E3 then has nothing left."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, pet = case["refund"], case["pet"]
    deposit_return = return_only(case, pet_refund(case), 2_000)
    result = confirm(
        case, record(case, return_command(case, refund, 500, settlement_refund(case, "pet", 2_000)))
    )
    assert {
        (paid["source_deposit_id"], paid["amount_usd_cents"]) for paid in result["refunds"]
    } == {(None, 500), (str(pet), 2_000)}
    assert (held(url, pet), deposit_left(url, deposit_return, pet)) == (0, 0)
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as emptied:
        record_held(case, held_command(case, deposit_return, settlement_refund(case, "pet", 2_000)))
    assert cause(emptied) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == before
    newest = return_only(case, pet_refund(case), 500)
    assert (
        held(url, pet),
        deposit_left(url, deposit_return, pet),
        deposit_left(url, newest, pet),
    ) == (500, 0, 500)
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as not_its_money:
        record_held(case, held_command(case, deposit_return, settlement_refund(case, "pet", 500)))
    assert cause(not_its_money) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == before
    taking = held_command(case, newest, settlement_refund(case, "pet", 500))
    [paid] = confirm_held(case, record_held(case, taking))["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 500)
    assert (
        held(url, pet),
        deposit_left(url, deposit_return, pet),
        deposit_left(url, newest, pet),
    ) == (0, 0, 0)
    with pytest.raises(FinalSettlementConflictError) as taken:
        record_held(case, held_command(case, newest, settlement_refund(case, "pet", 500)))
    assert cause(taken) == ("55000", NOTHING_LEFT)


def test_the_plan_check_takes_the_limit_per_deposit(migrated_database_url: str) -> None:
    """The plan check on its own (overlay ``held_left``, as a held-value correction records it).
    With 500 added to the Pet Deposit and a limit of 300 there, a Refund of 300 passes, 500 is
    refused (above the limit), 200 passes (owner answer 1 to Q-2026-10-09-65, "at most") and a plan
    that uses none of it is refused. Review round 1, with 1,000
    added to the Security Deposit and 800 to the Pet Deposit: a limit in the Pet Deposit refuses
    any use of the Security Deposit; a limit in the Security Deposit refunds it while the Pet
    Deposit keeps its money; with 600 of pet damage open (the Customer's Credit of 300 first), the
    Security Deposit may not pay it while the Pet Deposit keeps money this correction may not use
    (DL-032: the Pet Deposit pays pet damage first), and a limit in the Pet Deposit pays it. Review
    round 2: a Security Deposit limited to 300 may pay 300 of other debt while that pet damage stays
    open for the Pet Deposit. A malformed limit (also one above the 9e15 cap), or a limit together
    with the return-only flag, is invalid input (22023)."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, security = str(case["pet"]), str(case["security"])
    both = {security: 1_000, pet: 800}
    pet_damage = {f"INVOICE_LINE:{case['pet_line']}": 600}
    credit_first = SettlementCreditStep(case["new_credit"], LINE, case["pet_line"], 300)

    def check(
        steps: tuple[Any, ...],
        overlay: dict[str, Any],
        deposits: dict[str, int] | None = None,
        owed: dict[str, int] | None = None,
    ) -> None:
        with psycopg.connect(url) as connection:
            connection.execute(
                PLAN_RESULT,
                (
                    case["prop"],
                    case["human"],
                    case["settlement"],
                    Jsonb({"steps": [step.payload() for step in steps], "pet_remainder": None}),
                    Jsonb(
                        {
                            "obligations": owed or {},
                            "credits": {},
                            "deposits": deposits or {pet: 500},
                            **overlay,
                        }
                    ),
                ),
            )

    def refused(message: str, *arguments: Any) -> None:
        with pytest.raises(psycopg.Error) as error:
            check(*arguments)
        assert (error.value.sqlstate, error.value.diag.message_primary) == ("55000", message)

    def refund(deposit: str, amount: int) -> Any:
        return settlement_refund(case, deposit, amount)

    check((refund("pet", 300),), {"held_left": {pet: 300}})
    check((refund("pet", 300),), {"held_left": {pet: 300}, "hold_deposits": False})
    refused(BEYOND_LEFT, (refund("pet", 500),), {"held_left": {pet: 300}})
    check((refund("pet", 200),), {"held_left": {pet: 300}})
    refused(EVERY_BALANCE, (), {"held_left": {pet: 300}})
    refused(
        BEYOND_LEFT,
        (refund("security", 1_000), refund("pet", 800)),
        {"held_left": {pet: 800}},
        both,
    )
    check((refund("security", 1_000),), {"held_left": {security: 1_000}}, both)
    refused(
        "The Pet Deposit pays open pet damage before any other use or Refund",
        (
            credit_first,
            SettlementDepositStep(SECURITY, case["security"], LINE, case["pet_line"], 300),
            refund("security", 700),
        ),
        {"held_left": {security: 1_000}},
        both,
        pet_damage,
    )
    check(
        (
            credit_first,
            SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 300),
        ),
        {"held_left": {security: 300}},
        {security: 300, pet: 800},
        {**pet_damage, f"INVOICE_LINE:{case['other_line']}": 300},
    )
    check(
        (
            credit_first,
            SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 300),
            refund("pet", 500),
        ),
        {"held_left": {pet: 800}},
        both,
        pet_damage,
    )
    invalid_overlays: tuple[dict[str, Any], ...] = (
        {"held_left": {pet: 9_000_000_000_000_001}},
        {"held_left": []},
        {"held_left": None},
        {"held_left": {"not-a-uuid": 300}},
        {"held_left": {pet.upper(): 300}},
        {"held_left": {pet: -1}},
        {"held_left": {pet: 1.5}},
        {"held_left": {pet: "300"}},
        {"held_left": {pet: 300}, "hold_deposits": True},
    )
    for overlay in invalid_overlays:
        with pytest.raises(psycopg.Error) as invalid:
            check((refund("pet", 300),), overlay)
        assert invalid.value.sqlstate == "22023", overlay


def test_the_q65_case_is_settled_in_either_order(migrated_database_url: str) -> None:
    """Owner answer 1 to Q-2026-10-09-65, on the plan check called directly (the state that one
    correction leaves is the overlay of the next): the remaining Pet Deposit is a staff decision
    and the Customer has no Credit; the Pet Deposit holds 300 of a return E1 and the Security
    Deposit 200 of a return E2; 50 of pet damage and 100 of other debt are open. Security first:
    E2's correction pays the other debt and keeps 100 held (refunding them while pet damage stays
    open is refused); E1's correction pays the pet damage and refunds 250; E2's next correction
    refunds its 100. Pet first: E1's correction pays the pet damage and keeps 250 held (refunding
    them while other debt stays open, or paying it before the Security Deposit, is refused); E2's
    correction pays the other debt and refunds 100; E1's next correction refunds its 250. Both end
    with the pet damage paid by the Pet Deposit, the other debt by the Security Deposit and every
    Refund after the debt (DL-032, BR-SETTLE-008)."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    create_usd_refund(
        refunds(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", case["new_credit"], 300, "Customer asked"),
        actor=refund_actor(case["human"], case["prop"], "refunds.create"),
    )
    pet, security = str(case["pet"]), str(case["security"])
    pet_line = f"INVOICE_LINE:{case['pet_line']}"
    other_line = f"INVOICE_LINE:{case['other_line']}"
    pet_damage = SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 50)
    other_debt = SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 100)
    pet_rest = SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 100)

    def check(
        steps: tuple[Any, ...],
        limit: dict[str, int],
        deposits: dict[str, int],
        owed: dict[str, int],
        pet_remainder: Any = None,
    ) -> None:
        with psycopg.connect(url) as connection:
            connection.execute(
                PLAN_RESULT,
                (
                    case["prop"],
                    case["human"],
                    case["settlement"],
                    Jsonb(
                        {
                            "steps": [step.payload() for step in steps],
                            "pet_remainder": pet_remainder and pet_remainder.payload(),
                        }
                    ),
                    Jsonb(
                        {
                            "obligations": owed,
                            "credits": {},
                            "deposits": deposits,
                            "held_left": limit,
                        }
                    ),
                ),
            )

    def refused(message: str, *arguments: Any) -> None:
        with pytest.raises(psycopg.Error) as error:
            check(*arguments)
        assert (error.value.sqlstate, error.value.diag.message_primary) == ("55000", message)

    def refund(deposit: str, amount: int) -> Any:
        return settlement_refund(case, deposit, amount)

    start = {security: 200, pet: 300}
    both_owed = {pet_line: 50, other_line: 100}
    # Security first.
    refused(OPEN_DEBT, (other_debt, refund("security", 100)), {security: 200}, start, both_owed)
    check((other_debt,), {security: 200}, start, both_owed)
    check((pet_damage, refund("pet", 250)), {pet: 300}, {security: 100, pet: 300}, {pet_line: 50})
    check((refund("security", 100),), {security: 100}, {security: 100}, {})
    # Pet first.
    refused(OPEN_DEBT, (pet_damage, refund("pet", 250)), {pet: 300}, start, both_owed)
    refused(SECURITY_FIRST, (pet_damage, pet_rest), {pet: 300}, start, both_owed, STAFF)
    check((pet_damage,), {pet: 300}, start, both_owed)
    check(
        (other_debt, refund("security", 100)),
        {security: 200},
        {security: 200, pet: 250},
        {other_line: 100},
    )
    check((refund("pet", 250),), {pet: 250}, {pet: 250}, {})


def test_a_draft_recorded_without_the_limit_is_stale(migrated_database_url: str) -> None:
    """A held-value draft records its Deposit limit in its plan overlay: the Deposit form its
    Deposit's value left, the Credit form nothing (review round 1). A draft without it, as one
    recorded under migration 20261114_110 (inserted here with the same payload and source revision
    less the limit), is stale at the confirm and stays pending, in both forms; nothing moves. The
    recorded drafts are then confirmed."""
    url = migrated_database_url

    def older_copy(case: dict[str, Any], draft: object, limit: dict[str, int]) -> object:
        payload, revision, reason = one(
            url,
            "SELECT payload,source_revision,reason FROM app.financial_drafts WHERE id=%s",
            draft,
        )
        assert payload["plan_overlay"]["held_left"] == limit
        older = uuid4()
        overlay = dict(payload["plan_overlay"])
        del overlay["held_left"]
        with psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
                "'final_settlements.prepare',%s,%s,%s)",
                (
                    case["prop"],
                    case["human"],
                    older,
                    Jsonb({**payload, "plan_overlay": overlay}),
                    revision,
                    reason,
                ),
            )
        before = one(url, COUNTS)
        with pytest.raises(FinalSettlementStaleDraftError):
            confirm_held(case, older)
        assert (state(url, older), one(url, COUNTS)) == ("PENDING", before)
        return older

    case = {**closed_case(url), "url": url}
    pet = case["pet"]
    earlier = return_only(case, pet_refund(case), 1_000)
    draft = record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    older_copy(case, draft, {str(pet): 1_000})
    assert held(url, pet) == 1_000
    [paid] = confirm_held(case, draft)["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 1_000)
    assert held(url, pet) == 0
    credit_case = refunded_case(url)
    credit = credit_case["refund_credit"]
    credit_return = return_only(credit_case, credit_case["refund"], 400)
    credit_draft = record_held(credit_case, held_command(credit_case, credit_return))
    older_copy(credit_case, credit_draft, {})
    assert available(url, credit) == 400
    [credit_paid] = confirm_held(credit_case, credit_draft)["refunds"]
    assert (credit_paid["source_customer_credit_id"], credit_paid["amount_usd_cents"]) == (
        str(credit),
        400,
    )
    assert available(url, credit) == 0


def test_held_deposit_limit_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms a held-value Refund correction and no role
    calls the plan check or the step. The migration adds no function, table or trigger and changes
    only the four patched functions, each new body exactly the old one with its replacements, with
    privileges, owner, SECURITY DEFINER and settings kept; it is forward-only."""
    granted = {
        "app.record_settlement_held_value_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
        "app.confirm_settlement_held_value_refund(uuid,uuid,uuid,text)",
    }
    with psycopg.connect(migrated_database_url) as connection:
        for function in CHANGED:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in granted,), (
                    function,
                    role,
                )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261116_112")
    assert revision is not None and revision.down_revision == "20261115_111"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
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
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_held_deposit_limit") as temporary:
        alembic_command.upgrade(config, "20261115_111")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261116_112")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
