"""The shared DL-032 step of a post-settlement correction (V1-056 sub-slice 10c-2a-2).

Value a correction releases, or a Deposit holds again after closure, is used under the Settlement
rules before anything is refunded (owner answer 1 to Q-2026-10-07-41): each Customer's own Credit
pays that Customer's open debt on the Lease first (answer 1 to Q-2026-10-07-42), released Credit
pays its own Customer's debt before any Refund (answer 2), then the Deposits pay the Lease's open
debt in the DL-032 order and only the rest is refunded, with one Refund method, note, recipient and
agreement (answer 3 to Q-41). No correction variant uses the step yet, so these tests build the
correction by hand through the internal sub-slice 10a functions, in one owner transaction, as no
role can: the release (Deposit application reversals and a linked credit Adjustment) and then the
step.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from payment_test_support import seed_payment
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.move_out_inspection import (
    InspectionFinding,
    MoveOutInspectionConflictError,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
)
from relied_on_reversal_test_support import (
    ALLOCATION_TRIGGER,
    CLOSED,
    relied_on_refusal,
    relied_on_triggers_disabled,
)
from test_billing_service_migration import admin_database_url
from test_credit_migration import credit_id, recognize
from test_customer_ledger_migration import assert_reconciled
from test_deposit_application_reversal_migration import begin, reversal_case, reverse
from test_final_settlement_confirm_migration import confirm, this_month
from test_final_settlement_draft_migration import (
    CHOICE,
    LINE,
    PET_FIRST,
    PET_REST,
    STAFF,
    leaving_case,
    mixed_rent_case,
    normal_plan,
    record,
    two_signer_case,
)
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import charge_remaining, held, one, outstanding, today
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_settlement_correction_migration import (
    LINK,
    approver,
    credit_adjustment,
    invoice_of,
    settlement_row,
)
from test_settlement_extra_charge_migration import state

PLAN_RESULT = "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)"
POST_PLAN = "SELECT app.post_settlement_correction_plan(%s,%s,%s)"
LOCK_PLAN = "SELECT app.lock_settlement_correction_plan(%s)"
REFUND_WRITER = (
    "SELECT app.post_settlement_correction_deposit_refund(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)
INTERNAL = (
    "app.settlement_correction_overlay_amount(jsonb)",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
    "app.settlement_correction_credit_id(uuid,uuid)",
    "app.lock_settlement_correction_plan(uuid)",
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)",
    "app.assert_settlement_correction_credit_application_confirmed("
    "app.customer_credit_applications)",
    "app.assert_settlement_correction_deposit_refund_source(app.refunds)",
    "app.post_settlement_correction_deposit_refund(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,"
    "text,text,text)",
    "app.post_settlement_correction_plan(uuid,uuid,uuid)",
)
CHANGED = (
    "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)",
    "app.assert_final_settlement_credit_application_source()",
    "app.assert_final_settlement_credit_application_confirmed()",
    "app.validate_deposit_application()",
    "app.assert_final_settlement_refund_source(app.refunds)",
    "app.settlement_correction_refund_allowed(app.refunds)",
    "app.assert_settlement_correction_refund_detail()",
)
REASON = "The Damage charge was billed twice"
NOTE = "Cash handed over at the front desk"
STAFF_REASON = "The Customer will not pay the rest"
CREDIT_FIRST = (
    "Each Customer's Credit must pay that Customer's open debt, up to what it can pay, "
    "before any Deposit pays"
)
RELEASED_FIRST = (
    "Customer Credit the correction releases pays its own Customer's open debt on this Lease "
    "before any Refund"
)
NO_REFUND = "No Deposit Refund while the Lease still has open debt that the Deposit could pay"
NO_REFUND_SOURCE = "No Deposit Refund while the Lease still has open debt that a Deposit could pay"
NOT_EMPTIED = "Every remaining Deposit balance must be applied or refunded"
PET_FIRST_RULE = "The Pet Deposit pays open pet damage before any other use or Refund"
AFTER_SECURITY = (
    "The remaining Pet Deposit pays only debt still open after the Security Deposit has been used"
)
ONE_REFUND_SET = (
    "A post-settlement correction has one Refund method, reference note, recipient and agreement"
)
STALE = "The post-settlement correction draft is stale; its sources changed"
CLOSED_CREDIT = "A closed Final Settlement takes no new Credit application"
CLOSED_DEPOSIT = "A closed Final Settlement takes no new Deposit application"
ONLY_INSIDE = "The DL-032 step of a post-settlement correction runs only inside that correction"
PET_DAMAGE_ONLY = "The Pet Deposit first pays only valid pet damage"
# Sub-slice 10c-2a-4: a supersede on a Lease whose Final Settlement is closed.
SUPERSEDE_CLOSED = (
    "A move-out inspection of a Lease with a closed Final Settlement cannot be superseded"
)
CUSTOMER_ONLY = "At this termination only the Customer may choose to use the remaining Pet Deposit"
RENT_FIRST = (
    "Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless the "
    "Customer designated the line"
)
CREDIT_REVERSAL = (
    "INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,"
    "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,%s,clock_timestamp(),%s,"
    "'credits.applications.reverse')"
)


def closed_case(url: str) -> dict[str, Any]:
    """The 8c normal-end Settlement, confirmed and closed (sub-slice 8e-3): Credit 400, the Pet
    Deposit pays the pet damage line (12,500), the Security Deposit (10,000) and the rest of the
    Pet Deposit (2,100) pay the other damage line, and the Pet Deposit's rest (5,400) is refunded.
    After closure the Customer gets 300 of new Credit; a correction approver is ready."""
    case = leaving_case(url, start_offset=this_month(url))
    confirm(case, record(case, normal_plan(case), pet_remainder=STAFF))
    for stage, name in (
        ("SECURITY_EXPLICIT", "security_application"),
        ("PET_REMAINDER_EXPLICIT", "pet_rest_application"),
    ):
        case[name] = UUID(
            str(
                one(
                    url,
                    "SELECT id FROM app.deposit_applications "
                    "WHERE final_settlement_id=%s AND application_stage=%s",
                    case["settlement"],
                    stage,
                )[0]
            )
        )
    case["new_credit"] = new_credit(url, case, 300)
    case["person"] = approver(url)
    return case


def new_credit(url: str, case: dict[str, Any], amount: int, customer: UUID | None = None) -> UUID:
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=customer or case["customer"],
            amount=amount,
        )
    return credit_id(recognize(case["prop"], payment, case["human"], amount))


def adjust_line(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    line: UUID,
    adjustment: UUID,
    amount: int,
) -> None:
    """A credit Adjustment of one line through the existing writer (it sets every constraint
    IMMEDIATE), as the sub-slice 10a helper does for the other line."""
    found = connection.execute(
        "SELECT line.invoice_id,invoice.version FROM app.invoice_lines line "
        "JOIN app.invoices invoice ON invoice.id=line.invoice_id WHERE line.id=%s",
        (line,),
    ).fetchone()
    assert found is not None
    connection.execute(
        "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,%s,'CREDIT',%s,%s,%s,%s,%s)",
        (
            case["prop"],
            found[0],
            line,
            case["human"],
            uuid4(),
            "a" * 64,
            found[1],
            amount,
            f"correction/{uuid4()}",
            REASON,
            adjustment,
            uuid4(),
        ),
    )


def credit_step(
    credit: object, target: object, amount: int, target_kind: str = "INVOICE_LINE"
) -> dict[str, Any]:
    return {
        "kind": "CUSTOMER_CREDIT",
        "customer_credit_id": str(credit),
        "target_kind": target_kind,
        "target_id": str(target),
        "amount_usd_cents": amount,
        "customer_designation": None,
    }


def deposit_step(
    kind: str, deposit: object, target: object, amount: int, target_kind: str = "INVOICE_LINE"
) -> dict[str, Any]:
    return {
        "kind": kind,
        "deposit_id": str(deposit),
        "target_kind": target_kind,
        "target_id": str(target),
        "amount_usd_cents": amount,
    }


def refund_step(
    case: dict[str, Any], deposit: object, amount: int, **changes: Any
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "kind": "DEPOSIT_REFUNDS",
        "deposit_id": str(deposit),
        "amount_usd_cents": amount,
        "refund_method_id": str(case["cash"]),
        "reference_note": NOTE,
        "recipient_customer_id": str(case["customer"]),
        "signer_agreement": None,
    }
    step.update(changes)
    return step


def plan(*steps: dict[str, Any], pet_remainder: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"steps": list(steps), "pet_remainder": pet_remainder}


def overlay(
    obligations: dict[str, int] | None = None,
    deposits: dict[str, int] | None = None,
    credits: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "obligations": obligations or {},
        "deposits": deposits or {},
        "credits": credits or {},
    }


def released_overlay(case: dict[str, Any]) -> dict[str, Any]:
    """After the Security and remaining Pet Deposit applications on the other line are reversed
    and a 4,000 credit Adjustment removes part of it, the line owes 8,100 and the Deposits hold
    10,000 and 2,100 again."""
    return overlay(
        {f"INVOICE_LINE:{case['other_line']}": 8_100},
        {str(case["security"]): 10_000, str(case["pet"]): 2_100},
    )


def main_plan(case: dict[str, Any]) -> dict[str, Any]:
    """Credit 300 first, the Security Deposit pays the rest of the line, both rests refunded."""
    return plan(
        credit_step(case["new_credit"], case["other_line"], 300),
        deposit_step("SECURITY_DEPOSIT", case["security"], case["other_line"], 7_800),
        refund_step(case, case["security"], 2_200),
        refund_step(case, case["pet"], 2_100),
    )


def check(url: str, case: dict[str, Any], steps: dict[str, Any], shape: dict[str, Any]) -> Any:
    return one(
        url,
        PLAN_RESULT,
        case["prop"],
        case["human"],
        case["settlement"],
        Jsonb(steps),
        Jsonb(shape),
    )[0]


def plan_refusal(
    url: str, case: dict[str, Any], steps: dict[str, Any], shape: dict[str, Any]
) -> tuple[str | None, str | None]:
    with pytest.raises(psycopg.Error) as error:
        check(url, case, steps, shape)
    return error.value.sqlstate, error.value.diag.message_primary


def plan_draft(
    url: str,
    case: dict[str, Any],
    steps: dict[str, Any],
    shape: dict[str, Any],
    result: dict[str, Any] | None = None,
) -> UUID:
    """A SETTLEMENT_CORRECTION draft holding the plan, its overlay and the check's result, as a
    variant recorder (10c-2a-3, 10c-2b, 10d) will write it."""
    if result is None:
        result = {k: v for k, v in check(url, case, steps, shape).items() if k != "source_revision"}
    draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "'final_settlements.prepare',%s,NULL,%s)",
            (
                case["prop"],
                case["human"],
                draft,
                Jsonb(
                    {
                        "final_settlement_id": str(case["settlement"]),
                        "plan": steps,
                        "plan_overlay": shape,
                        "plan_result": result,
                    }
                ),
                REASON,
            ),
        )
    return draft


def release(connection: psycopg.Connection[Any], case: dict[str, Any], draft: UUID) -> UUID:
    """The variant's part, by hand: the step's locks, the correction, the reversal of the two
    Deposit applications on the other line and a linked 4,000 credit Adjustment of that line."""
    connection.execute(LOCK_PLAN, (draft,))
    correction = begin(connection, case, draft)
    reverse(connection, correction, case["security_application"], case["person"])
    reverse(connection, correction, case["pet_rest_application"], case["person"])
    adjustment = uuid4()
    connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
    credit_adjustment(connection, case, adjustment, 4_000)
    return correction


def release_line(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    draft: UUID,
    applications: tuple[UUID, ...],
    line: UUID,
    amount: int,
) -> UUID:
    """The variant's part, by hand, for one line: the step's locks, the correction, the reversal
    of the line's Deposit applications and a linked credit Adjustment of that line."""
    connection.execute(LOCK_PLAN, (draft,))
    correction = begin(connection, case, draft)
    for application in applications:
        reverse(connection, correction, application, case["person"])
    adjustment = uuid4()
    connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
    adjust_line(connection, case, line, adjustment, amount)
    return correction


def pet_first_application(url: str, case: dict[str, Any]) -> UUID:
    return UUID(
        str(
            one(
                url,
                "SELECT id FROM app.deposit_applications "
                "WHERE final_settlement_id=%s AND application_stage='PET_RELATED_FIRST'",
                case["settlement"],
            )[0]
        )
    )


def blocked_by(application_name: str, holder: psycopg.Connection[Any]) -> bool:
    """Whether the session with this application name, within 10 seconds, is blocked by the
    holder's transaction while it holds or waits for a lock on app.leases (any lock on that
    relation; round-3 hardening, carried into sub-slice 10c-2a-3)."""
    found = holder.execute("SELECT 'app.leases'::regclass::oid").fetchone()
    assert found is not None
    with psycopg.connect(admin_database_url(), autocommit=True) as observer:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            waiting = observer.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity activity "
                "WHERE activity.application_name=%s AND activity.datname=%s "
                "AND activity.wait_event_type='Lock' "
                "AND %s=ANY(pg_catalog.pg_blocking_pids(activity.pid)) "
                "AND EXISTS(SELECT 1 FROM pg_catalog.pg_locks lock WHERE lock.pid=activity.pid "
                "AND lock.relation=%s AND lock.database=(SELECT oid FROM pg_catalog.pg_database "
                "WHERE datname=%s)))",
                (
                    application_name,
                    holder.info.dbname,
                    holder.info.backend_pid,
                    found[0],
                    holder.info.dbname,
                ),
            ).fetchone()
            if waiting == (True,):
                return True
            time.sleep(0.01)
    return False


def blocked_on_lease_row(application_name: str, holder: psycopg.Connection[Any]) -> bool:
    """As blocked_by, and the waiter waits on a Lease row, not on a Final Settlement row: while
    it sleeps on the holder's transaction it holds the tuple lock of an app.leases row and no
    tuple lock of an app.final_settlements row (sub-slice 10c-2a-4 review round 1; blocked_by
    alone accepts any lock on app.leases, which every inspection command holds)."""
    if not blocked_by(application_name, holder):
        return False
    relations = holder.execute(
        "SELECT 'app.leases'::regclass::oid,'app.final_settlements'::regclass::oid"
    ).fetchone()
    assert relations is not None
    with psycopg.connect(admin_database_url(), autocommit=True) as observer:
        found = observer.execute(
            "SELECT bool_or(lock.relation=%s AND lock.locktype='tuple'),"
            "bool_or(lock.relation=%s AND lock.locktype='tuple') "
            "FROM pg_catalog.pg_stat_activity activity "
            "JOIN pg_catalog.pg_locks lock ON lock.pid=activity.pid "
            "WHERE activity.application_name=%s AND activity.datname=%s "
            "AND activity.wait_event_type='Lock'",
            (relations[0], relations[1], application_name, holder.info.dbname),
        ).fetchone()
    assert found is not None
    return found[0] is True and found[1] is not True


def post(connection: psycopg.Connection[Any], case: dict[str, Any], draft: UUID) -> Any:
    found = connection.execute(POST_PLAN, (case["prop"], case["person"], draft)).fetchone()
    assert found is not None
    return found[0]


def failure(
    url: str, action: Callable[[psycopg.Connection[Any]], object]
) -> tuple[str | None, str | None]:
    """The SQLSTATE and message of an action that must fail, also at commit: the deferred checks
    run as a commit would run them, and the transaction then rolls back, also when the action
    unexpectedly succeeds (review round 1 of sub-slice 10c-2a-3), so a failing test leaves
    nothing behind."""
    with pytest.raises(psycopg.Error) as error, psycopg.connect(url) as connection:
        try:
            action(connection)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            connection.rollback()
    return error.value.sqlstate, error.value.diag.message_primary


def test_released_deposit_value_pays_the_open_debt_after_credit_and_the_rest_is_refunded(
    migrated_database_url: str,
) -> None:
    """DL-032, BR-SETTLE-004, BR-SETTLE-008, BR-SETTLE-013 and the owner answers to
    Q-2026-10-07-41 and Q-2026-10-07-42: after the correction gives the Deposits 12,100 back and
    the line owes 8,100, the Customer's own Credit pays first (300), the Security Deposit pays the
    rest of the line (7,800) and only what remains in each Deposit is refunded (2,200 and 2,100).
    Every record is linked to the correction before it is written; the closed Settlement row is
    unchanged; both Deposits end empty, the line owes nothing and the ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    security, pet, other_line, customer = (
        case["security"],
        case["pet"],
        case["other_line"],
        case["customer"],
    )
    assert (held(url, security), held(url, pet), outstanding(url, other_line)) == (0, 0, 0)
    before = settlement_row(url, case["settlement"])
    # The check before the release, with the overlay of what the correction will release.
    result = check(url, case, main_plan(case), released_overlay(case))
    assert {key: value for key, value in result.items() if key != "source_revision"} == {
        "lease_id": str(case["lease"]),
        "termination_ground": None,
        "pet_remainder_chosen_by": "CUSTOMER_OR_STAFF_WITH_REASON",
        "deposit_ids": sorted([str(security), str(pet)]),
        "open_total_usd_cents": 8_100,
        "closing_balance_usd_cents": 0,
        "closing_balances": [],
        "credit_left": {},
    }
    assert str(result["source_revision"]).startswith("settlement-correction-plan:")
    draft = plan_draft(url, case, main_plan(case), released_overlay(case))
    with psycopg.connect(url) as connection:
        correction = release(connection, case, draft)
        written = post(connection, case, draft)
    assert state(url, draft) == "CONFIRMED"
    assert (written["closing_balance_usd_cents"], written["credit_left"]) == (0, {})
    assert (held(url, security), held(url, pet), outstanding(url, other_line)) == (0, 0, 0)
    assert one(url, "SELECT app.credit_available_value(%s)", case["new_credit"]) == (0,)
    assert settlement_row(url, case["settlement"]) == before
    # The Credit step: a Credit application of the Settlement under financial.approve, by the
    # approver, linked to the correction, with the basis BR-CREDIT-006 gives a Damage Invoice.
    credit_application, deposit_application = (
        UUID(written["credit_application_ids"][0]),
        UUID(written["deposit_application_ids"][0]),
    )
    refund_ids = [UUID(refund) for refund in written["refund_ids"]]
    assert (len(written["credit_application_ids"]), len(written["deposit_application_ids"])) == (
        1,
        1,
    )
    assert one(
        url,
        "SELECT final_settlement_id,authorization_reference,actor_id,amount_usd_cents,"
        "within_invoice_basis,customer_credit_id FROM app.customer_credit_applications WHERE id=%s",
        credit_application,
    ) == (
        case["settlement"],
        "financial.approve",
        case["person"],
        300,
        "OTHER_APPLICABLE_OBLIGATION",
        case["new_credit"],
    )
    # The Deposit application: the next order number of the Settlement, its stage, the reason.
    assert one(
        url,
        "SELECT deposit_id,application_stage,amount_usd_cents,application_order,actor_id,reason "
        "FROM app.deposit_applications WHERE id=%s",
        deposit_application,
    ) == (security, "SECURITY_EXPLICIT", 7_800, 4, case["person"], REASON)
    # The Deposit Refunds, in Deposit id order, each with its details row naming the Deposit.
    refunds = [
        one(
            url,
            "SELECT refund.source_deposit_id,refund.usd_accounting_value_cents,"
            "refund.recipient_customer_id,refund.processed_by,refund.authorization_reference,"
            "detail.deposit_id,detail.signer_agreement,detail.settlement_correction_id,"
            "detail.draft_id,detail.reference_note FROM app.refunds refund "
            "JOIN app.settlement_correction_refund_details detail ON detail.refund_id=refund.id "
            "WHERE refund.id=%s",
            refund,
        )
        for refund in refund_ids
    ]
    amounts = {security: 2_200, pet: 2_100}
    assert [row[0] for row in refunds] == sorted([security, pet])
    for row in refunds:
        assert row == (
            row[0],
            amounts[row[0]],
            customer,
            case["person"],
            "financial.approve",
            row[0],
            None,
            correction,
            draft,
            NOTE,
        )
    # Every record is the effect of the correction, after the release records.
    links = one(
        url,
        "SELECT array_agg(COALESCE(customer_credit_application_id,deposit_application_id,"
        "refund_id) ORDER BY effect_sequence) FILTER (WHERE customer_credit_application_id "
        "IS NOT NULL OR deposit_application_id IS NOT NULL OR refund_id IS NOT NULL) "
        "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s",
        correction,
    )[0]
    assert links == [credit_application, deposit_application, *refund_ids]
    with psycopg.connect(url) as connection:
        position = assert_reconciled(connection, customer)
    assert (position.security_deposit, position.pet_deposit) == (0, 0)
    # A correction's Credit application changes only through another correction (8e-2).
    assert failure(
        url,
        lambda connection: connection.execute(
            "INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,"
            "reason,occurred_at,actor_id,authorization_reference) VALUES "
            "(%s,%s,'Reversed by mistake',clock_timestamp(),%s,'credits.applications.reverse')",
            (uuid4(), credit_application, case["human"]),
        ),
    ) == (
        "P5S01",
        "A Final Settlement Credit application changes only through a post-settlement correction",
    )


def test_credit_released_from_a_payment_pays_its_customer_s_debt_before_the_deposit(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014 and owner answers 1 and 2 to Q-2026-10-07-42: a plan key may name the Credit
    that value released from a Payment allocation by the same correction becomes; that released
    Credit pays its own Customer's open debt first (here the pet damage the Pet Deposit gets back)
    and the Pet Deposit pays the rest; a draft whose released allocation the correction did not
    release is stale and stays pending."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    prop, human, customer = case["prop"], case["human"], case["customer"]
    other_line, pet_line, pet = case["other_line"], case["pet_line"], case["pet"]
    pay(url, prop, human, customer, invoice_of(url, other_line), other_line, 12_500)
    confirm(
        case,
        record(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, pet_line, 400),
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_100),
                settlement_refund(case, "security", 10_000),
                settlement_refund(case, "pet", 7_900),
            ),
        ),
    )
    case["person"] = approver(url)
    pet_first = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.deposit_applications WHERE final_settlement_id=%s",
                case["settlement"],
            )[0]
        )
    )
    allocation = UUID(
        str(
            one(
                url,
                "SELECT allocation.id FROM app.payment_allocations allocation "
                "WHERE allocation.invoice_id=%s AND NOT EXISTS(SELECT 1 FROM "
                "app.payment_allocation_reversals reversal "
                "WHERE reversal.payment_allocation_id=allocation.id)",
                invoice_of(url, other_line),
            )[0]
        )
    )
    shape = overlay(
        {f"INVOICE_LINE:{pet_line}": 12_100},
        {str(pet): 12_100},
        {
            str(allocation): {
                "customer_id": str(customer),
                "add_usd_cents": 5_000,
                "released_payment_allocation_id": str(allocation),
            }
        },
    )
    steps = plan(
        credit_step(allocation, pet_line, 5_000),
        deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, 7_100),
        refund_step(case, pet, 5_000),
    )
    # The released Credit must pay its own Customer's debt before the Pet Deposit does.
    assert plan_refusal(
        url,
        case,
        plan(deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, 12_100)),
        shape,
    ) == ("55000", CREDIT_FIRST)
    draft = plan_draft(url, case, steps, shape)
    assert check(url, case, steps, shape)["credit_left"] == {str(allocation): 0}

    def unreleased(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, draft)
        reverse(connection, correction, pet_first, case["person"])
        post(connection, case, draft)

    assert failure(url, unreleased) == ("P5S02", STALE)
    assert state(url, draft) == "PENDING"
    # The Credit Refund check of sub-slice 10c-1b accepts a correction's Credit Refund only when
    # its details name no Deposit (review round 1); here the recipient is the payer, and the check
    # runs inside a correction that rolls back.
    with psycopg.connect(url) as connection:
        connection.execute(LOCK_PLAN, (draft,))
        correction = begin(connection, case, draft)
        reverse(connection, correction, pet_first, case["person"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        # Since sub-slice 10h-1 the ordinary writer's release reversal can no longer be written
        # here: a real correction links that reversal first, and this hand-built one cannot (the
        # writer makes its id). The refusal is asserted, then the release is written with only
        # the 10h-1 allocation trigger disabled in this transaction (owner answer (a) to
        # Q-2026-10-19-142).
        assert relied_on_refusal(
            connection, lambda: credit_adjustment(connection, case, adjustment, 5_000)
        ) == ("P5S01", CLOSED)
        with relied_on_triggers_disabled(connection, (ALLOCATION_TRIGGER,)):
            credit_adjustment(connection, case, adjustment, 5_000)
        found = connection.execute(
            "SELECT customer_credit_id FROM app.invoice_credit_excess_releases "
            "WHERE invoice_adjustment_id=%s",
            (adjustment,),
        ).fetchone()
        assert found is not None
        connection.execute(
            "SET CONSTRAINTS app.settlement_correction_refund_details_refund_id_fkey,"
            "app.settlement_correction_refund_details_approver,"
            "app.settlement_correction_effects_refund_id_fkey DEFERRED"
        )
        allowed = []
        for deposit in (None, pet):
            refund = uuid4()
            connection.execute(LINK, (correction, "refund_id", refund))
            connection.execute(
                "INSERT INTO app.settlement_correction_refund_details(refund_id,"
                "settlement_correction_id,draft_id,refund_method_id,reference_note,recorded_at,"
                "deposit_id) VALUES (%s,%s,%s,%s,%s,clock_timestamp(),%s)",
                (refund, correction, draft, case["cash"], NOTE, deposit),
            )
            row = connection.execute(
                "SELECT app.settlement_correction_refund_allowed("
                "jsonb_populate_record(NULL::app.refunds,%s))",
                (
                    Jsonb(
                        {
                            "id": str(refund),
                            "recipient_customer_id": str(customer),
                            "source_customer_credit_id": str(found[0]),
                            "usd_accounting_value_cents": 100,
                            "processed_by": str(case["person"]),
                        }
                    ),
                ),
            ).fetchone()
            assert row is not None
            allowed.append(row[0])
        assert allowed == [True, False]
        connection.rollback()
    assert state(url, draft) == "PENDING"
    with psycopg.connect(url) as connection:
        connection.execute(LOCK_PLAN, (draft,))
        correction = begin(connection, case, draft)
        reverse(connection, correction, pet_first, case["person"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        # The same hand-built release as above (sub-slice 10h-1).
        assert relied_on_refusal(
            connection, lambda: credit_adjustment(connection, case, adjustment, 5_000)
        ) == ("P5S01", CLOSED)
        with relied_on_triggers_disabled(connection, (ALLOCATION_TRIGGER,)):
            credit_adjustment(connection, case, adjustment, 5_000)
        written = post(connection, case, draft)
    released = UUID(str(written["credit_ids"][str(allocation)]))
    assert one(
        url,
        "SELECT customer_id,source_payment_id=(SELECT payment_id FROM app.payment_allocations "
        "WHERE id=%s) FROM app.customer_credits WHERE id=%s",
        allocation,
        released,
    ) == (customer, True)
    assert one(
        url,
        "SELECT customer_credit_id,amount_usd_cents,final_settlement_id "
        "FROM app.customer_credit_applications WHERE id=%s",
        written["credit_application_ids"][0],
    ) == (released, 5_000, case["settlement"])
    assert written["credit_left"] == {str(allocation): 0}
    assert (outstanding(url, pet_line), outstanding(url, other_line), held(url, pet)) == (0, 0, 0)
    assert one(url, "SELECT app.credit_available_value(%s)", released) == (0,)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_the_correction_plan_follows_every_settlement_rule_after_closure(
    migrated_database_url: str,
) -> None:
    """The Settlement plan rules after closure (owner answer 1 to Q-2026-10-07-41) and the
    correction rules (answers 1 and 2 to Q-2026-10-07-42, answer 3 to Q-41): an open Settlement,
    Credit not used first, released Credit refunded while its Customer owes, a Refund while debt
    remains, a Deposit not emptied, steps out of the DL-032 order, a Deposit of the wrong type for
    its step, a Pet Deposit first step on a line that is not pet damage, pet damage first, the
    remaining Pet Deposit before the Security Deposit is used, mixed Refund details, a Refund to
    another Customer without the agreement, a Deposit that holds nothing, a waiting draft, and
    malformed or foreign overlays are refused."""
    url = migrated_database_url
    case = closed_case(url)
    other_line, pet_line = case["other_line"], case["pet_line"]
    security, pet, credit = case["security"], case["pet"], case["new_credit"]
    released = released_overlay(case)
    open_case = leaving_case(url, start_offset=this_month(url))
    assert plan_refusal(url, open_case, plan(), overlay()) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    assert plan_refusal(
        url,
        case,
        plan(
            deposit_step("SECURITY_DEPOSIT", security, other_line, 8_100),
            refund_step(case, security, 1_900),
            refund_step(case, pet, 2_100),
        ),
        released,
    ) == ("55000", CREDIT_FIRST)
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_000),
            refund_step(case, security, 3_000),
            refund_step(case, pet, 2_100),
        ),
        released,
    ) == ("55000", NO_REFUND)
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_800),
            refund_step(case, security, 2_200),
        ),
        released,
    ) == ("55000", NOT_EMPTIED)
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_800),
            refund_step(case, security, 2_200),
            refund_step(case, pet, 2_100, reference_note="Bank transfer to the usual account"),
        ),
        released,
    ) == ("22023", ONE_REFUND_SET)
    # DL-032: the step order, the Deposit type of each step and pet damage for the Pet Deposit's
    # first step (review round 2).
    assert plan_refusal(
        url,
        case,
        plan(
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_800),
            credit_step(credit, other_line, 300),
        ),
        released,
    ) == ("22023", "Post-settlement correction steps must follow the DL-032 order")
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("SECURITY_DEPOSIT", pet, other_line, 2_100),
        ),
        released,
    ) == ("55000", "The Deposit type does not match the DL-032 step")
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, other_line, 2_100),
        ),
        released,
    ) == ("55000", PET_DAMAGE_ONLY)
    # Released Credit (here the Customer's Credit named as released) must pay its own Customer's
    # open debt first; with no Deposit holding money the other Credit rule does not apply.
    as_released = overlay(
        {f"INVOICE_LINE:{other_line}": 8_100},
        credits={
            str(credit): {
                "customer_id": str(case["customer"]),
                "add_usd_cents": 0,
                "released_payment_allocation_id": None,
            }
        },
    )
    assert plan_refusal(url, case, plan(), as_released) == ("55000", RELEASED_FIRST)
    used = check(url, case, plan(credit_step(credit, other_line, 300)), as_released)
    assert (used["closing_balance_usd_cents"], used["credit_left"]) == (7_800, {str(credit): 0})
    # The Pet Deposit pays open pet damage before any Refund.
    assert plan_refusal(
        url,
        case,
        plan(credit_step(credit, pet_line, 300), refund_step(case, pet, 1_000)),
        overlay({f"INVOICE_LINE:{pet_line}": 1_000}, {str(pet): 1_000}),
    ) == ("55000", PET_FIRST_RULE)
    # The owner answer to choice (4a): the remaining Pet Deposit only after the Security Deposit.
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("PET_DEPOSIT_REMAINDER", pet, other_line, 1_800),
            refund_step(case, security, 10_000),
            refund_step(case, pet, 300),
            pet_remainder={
                "basis": "STAFF_REASON",
                "customer_choice": None,
                "staff_reason": STAFF_REASON,
            },
        ),
        overlay(
            {f"INVOICE_LINE:{other_line}": 2_100},
            {str(security): 10_000, str(pet): 2_100},
        ),
    ) == ("55000", AFTER_SECURITY)
    # BR-REFUND-015: another Customer only as a signed Signer with the written agreement.
    assert plan_refusal(
        url,
        case,
        plan(
            credit_step(credit, other_line, 300),
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_800),
            refund_step(case, security, 2_200, recipient_customer_id=str(case["person"])),
            refund_step(case, pet, 2_100, recipient_customer_id=str(case["person"])),
        ),
        released,
    ) == ("22023", "A Refund to another Signer needs the written agreement of all Signers")
    # Only a Deposit that follows DL-032 and holds money may be refunded.
    assert plan_refusal(url, case, plan(refund_step(case, security, 100)), overlay()) == (
        "55000",
        "Only a Deposit that follows DL-032 and holds money may be refunded",
    )
    # Malformed and foreign overlays.
    assert plan_refusal(url, case, plan(), {"obligations": {}, "deposits": {}}) == (
        "22023",
        "Post-settlement correction overlay is invalid",
    )
    assert plan_refusal(
        url, case, plan(), overlay({f"INVOICE_LINE:{str(other_line).upper()}": 1})
    ) == ("22023", "Post-settlement correction overlay is invalid")
    assert plan_refusal(url, case, plan(), overlay({f"INVOICE_LINE:{uuid4()}": 1})) == (
        "55000",
        "The overlay names an obligation outside this Final Settlement",
    )
    assert plan_refusal(url, case, plan(), overlay(deposits={str(uuid4()): 1})) == (
        "55000",
        "The overlay names a Deposit outside this Final Settlement",
    )
    assert plan_refusal(
        url,
        case,
        plan(),
        overlay(
            credits={
                str(credit): {
                    "customer_id": str(case["person"]),
                    "add_usd_cents": 1,
                    "released_payment_allocation_id": None,
                }
            }
        ),
    ) == ("55000", "The overlay names a Customer Credit outside this Final Settlement")
    assert plan_refusal(url, case, {"steps": "none"}, overlay()) == (
        "22023",
        "Post-settlement correction plan is invalid",
    )
    # The owner's 8r rule and the Settlement's pending-draft rule: a waiting Refund draft of the
    # Customer's Credit blocks the step.
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'REFUND','refunds.create',%s,NULL,%s)",
            (
                case["prop"],
                case["human"],
                uuid4(),
                Jsonb({"variant": "USD", "source_kind": "CREDIT", "source_id": str(credit)}),
                "Refund the new Credit",
            ),
        )
    assert plan_refusal(url, case, main_plan(case), released) == (
        "55000",
        "A draft on a source of this Final Settlement is waiting",
    )


def test_the_relaxed_checks_accept_only_a_correction_s_own_records(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-013, BR-AUTH-010 and owner answer 3 to Q-2026-10-07-41: after closure a Credit
    application of the Settlement, a Deposit application and a Deposit Refund are accepted only as
    the own record of a correction confirmed in the same transaction, written by its approver, that
    matches its plan, in the DL-032 order, once per Deposit; the step runs only inside its
    correction, for that correction's approver and at READ COMMITTED, and a draft whose result no
    longer matches is stale. Each refused attempt rolls back and the draft stays pending."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, person = case["prop"], case["human"], case["person"]
    security, other_line, credit = case["security"], case["other_line"], case["new_credit"]
    draft = plan_draft(url, case, main_plan(case), released_overlay(case))
    other_invoice = invoice_of(url, other_line)

    def credit_application(
        connection: psycopg.Connection[Any], actor: UUID, amount: int, *, link: UUID | None
    ) -> None:
        application = uuid4()
        if link is not None:
            # The release's existing Adjustment writer set every constraint IMMEDIATE; a writer
            # links before it writes, with the link key deferred (as the step does).
            connection.execute(
                "SET CONSTRAINTS "
                "app.settlement_correction_effects_customer_credit_application__fkey DEFERRED"
            )
            connection.execute(LINK, (link, "customer_credit_application_id", application))
        connection.execute(
            "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,"
            "invoice_id,final_settlement_id,amount_usd_cents,within_invoice_basis,occurred_at,"
            "actor_id,authorization_reference) VALUES (%s,%s,'INVOICE',%s,%s,%s,"
            "'OTHER_APPLICABLE_OBLIGATION',clock_timestamp(),%s,'financial.approve')",
            (application, credit, other_invoice, case["settlement"], amount, actor),
        )

    def deposit_application(
        connection: psycopg.Connection[Any],
        actor: UUID,
        *,
        link: UUID | None,
        amount: int = 100,
        order: int = 9,
        stage: str = "SECURITY_EXPLICIT",
        deposit: UUID | None = None,
    ) -> None:
        application = uuid4()
        if link is not None:
            connection.execute(
                "SET CONSTRAINTS app.settlement_correction_effects_deposit_application_id_fkey "
                "DEFERRED"
            )
            connection.execute(LINK, (link, "deposit_application_id", application))
        connection.execute(
            "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,%s,'INVOICE_LINE',%s,%s,%s,%s)",
            (
                prop,
                actor,
                case["settlement"],
                application,
                deposit or security,
                stage,
                other_line,
                amount,
                order,
                REASON,
            ),
        )

    def refund_rows(
        connection: psycopg.Connection[Any],
        correction: UUID,
        detail_deposit: UUID,
        *,
        source_deposit: UUID | None = None,
        source_credit: UUID | None = None,
    ) -> None:
        """A Refund and its correction details row written by hand, linked to the correction."""
        refund = uuid4()
        connection.execute(
            "SET CONSTRAINTS app.settlement_correction_refund_details_refund_id_fkey,"
            "app.settlement_correction_refund_details_approver,"
            "app.settlement_correction_effects_refund_id_fkey DEFERRED"
        )
        connection.execute(LINK, (correction, "refund_id", refund))
        connection.execute(
            "INSERT INTO app.settlement_correction_refund_details(refund_id,"
            "settlement_correction_id,draft_id,refund_method_id,reference_note,recorded_at,"
            "deposit_id) "
            "VALUES (%s,%s,%s,%s,%s,clock_timestamp(),%s)",
            (refund, correction, draft, case["cash"], NOTE, detail_deposit),
        )
        connection.execute(
            "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,"
            "source_customer_credit_id,usd_accounting_value_cents,refund_currency,"
            "refund_amount_minor,reason,processed_at,processed_by,authorization_reference) "
            "VALUES (%s,%s,%s,%s,%s,100,'USD',100,%s,clock_timestamp(),%s,%s)",
            (
                refund,
                f"REF-{refund}",
                case["customer"],
                source_deposit,
                source_credit,
                REASON,
                person,
                "financial.approve" if source_deposit is not None else "refunds.create",
            ),
        )

    def deposit_refund(
        connection: psycopg.Connection[Any], correction: UUID, actor: UUID, amount: int, **kw: Any
    ) -> None:
        connection.execute(
            REFUND_WRITER,
            (
                prop,
                actor,
                correction,
                draft,
                security,
                amount,
                kw.get("recipient", case["customer"]),
                case["cash"],
                NOTE,
                kw.get("agreement"),
                REASON,
            ),
        )

    # Without a correction every one of them stays refused after closure.
    assert failure(
        url, lambda connection: credit_application(connection, person, 300, link=None)
    ) == ("55000", CLOSED_CREDIT)
    assert failure(url, lambda connection: deposit_application(connection, person, link=None)) == (
        "55000",
        CLOSED_DEPOSIT,
    )
    assert failure(
        url,
        lambda connection: connection.execute(
            "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,"
            "usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,"
            "processed_by,authorization_reference) VALUES (%s,%s,%s,%s,100,'USD',100,%s,"
            "clock_timestamp(),%s,'financial.approve')",
            (uuid4(), f"REF-{uuid4()}", case["customer"], security, REASON, person),
        ),
    ) == (
        "23514",
        "A Deposit Refund needs its Reservation, Pet Refund review or Final Settlement source",
    )
    # The step runs only inside its own correction.
    assert failure(url, lambda connection: post(connection, case, draft)) == ("23514", ONLY_INSIDE)
    # Inside a live correction it runs only for that correction's approver, and only at READ
    # COMMITTED (review round 2); each attempt rolls back and the draft stays pending.
    someone_else = approver(url)

    def another_person(connection: psycopg.Connection[Any]) -> None:
        connection.execute(LOCK_PLAN, (draft,))
        begin(connection, case, draft)
        connection.execute(POST_PLAN, (prop, someone_else, draft))

    def repeatable_read(connection: psycopg.Connection[Any]) -> None:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.execute(LOCK_PLAN, (draft,))
        begin(connection, case, draft)
        post(connection, case, draft)

    assert failure(url, another_person) == ("23514", ONLY_INSIDE)
    assert failure(url, repeatable_read) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert state(url, draft) == "PENDING"

    def inside(action: Callable[[psycopg.Connection[Any], UUID], object]) -> Any:
        def run(connection: psycopg.Connection[Any]) -> None:
            action(connection, release(connection, case, draft))

        return failure(url, run)

    def after_step(action: Callable[[psycopg.Connection[Any], UUID], object]) -> Any:
        def run(connection: psycopg.Connection[Any], correction: UUID) -> None:
            post(connection, case, draft)
            action(connection, correction)

        return inside(run)

    # Credit applications: the approver, a step of the plan, before the Deposit applications.
    assert inside(
        lambda connection, correction: credit_application(connection, human, 300, link=correction)
    ) == (
        "42501",
        "A post-settlement correction Credit application is written by the correction's approver "
        "under financial.approve",
    )
    assert inside(
        lambda connection, correction: credit_application(connection, person, 200, link=correction)
    ) == (
        "23514",
        "A post-settlement correction Credit application must be a Credit step of its correction",
    )
    assert after_step(
        lambda connection, correction: credit_application(connection, person, 300, link=correction)
    ) == (
        "55000",
        "Customer Credit is applied before the correction's Deposit applications and Refunds",
    )
    # Deposit applications: the approver, before the correction's Refunds.
    assert inside(
        lambda connection, correction: deposit_application(connection, human, link=correction)
    ) == (
        "23514",
        "A post-settlement correction Deposit application is written by the correction's "
        "approver, after it",
    )
    assert after_step(
        lambda connection, correction: deposit_application(connection, person, link=correction)
    ) == ("55000", "Deposit applications are recorded before the correction's Refunds")
    # A Deposit step of the plan, exactly as prepared, each step once (review round 1).
    off_plan = (
        "23514",
        "A post-settlement correction Deposit application must be a Deposit step of its "
        "correction, once",
    )
    assert (
        inside(
            lambda connection, correction: deposit_application(connection, person, link=correction)
        )
        == off_plan
    )

    def twice(connection: psycopg.Connection[Any], correction: UUID) -> None:
        deposit_application(connection, person, link=correction, amount=7_800, order=9)
        deposit_application(connection, person, link=correction, amount=7_800, order=10)

    assert inside(twice) == off_plan
    # The DL-032 stage order holds within the correction: no Security Deposit step after a
    # remaining Pet Deposit step (the plan below is stored as given, without its check).
    ordered = plan_draft(
        url,
        case,
        plan(
            deposit_step("SECURITY_DEPOSIT", security, other_line, 7_000),
            deposit_step("PET_DEPOSIT_REMAINDER", case["pet"], other_line, 800),
        ),
        released_overlay(case),
        {},
    )

    def pet_rest_then_security(connection: psycopg.Connection[Any]) -> None:
        correction = release(connection, case, ordered)
        deposit_application(
            connection,
            person,
            link=correction,
            amount=800,
            order=9,
            stage="PET_REMAINDER_EXPLICIT",
            deposit=case["pet"],
        )
        deposit_application(connection, person, link=correction, amount=7_000, order=10)

    assert failure(url, pet_rest_then_security) == (
        "23514",
        "Deposit applications follow the DL-032 order",
    )
    # Deposit Refunds: the approver, BR-REFUND-015, a step of the plan, once per Deposit, and no
    # Refund while debt a Deposit could pay remains.
    assert inside(
        lambda connection, correction: deposit_refund(connection, correction, human, 2_200)
    ) == (
        "42501",
        "A post-settlement correction Deposit Refund is processed by the correction's approver",
    )
    assert inside(
        lambda connection, correction: deposit_refund(
            connection, correction, person, 2_200, recipient=case["person"]
        )
    ) == (
        "23514",
        "A Refund to another Signer needs a signed Signer and the written agreement of all Signers",
    )
    assert inside(
        lambda connection, correction: deposit_refund(connection, correction, person, 2_000)
    ) == (
        "23514",
        "A post-settlement correction Deposit Refund must be a Refund step of its correction, "
        "once per Deposit",
    )
    assert inside(
        lambda connection, correction: deposit_refund(connection, correction, person, 2_200)
    ) == ("55000", NO_REFUND_SOURCE)
    # Once per Deposit per correction: the details key refuses a second Refund (review round 1).
    once = after_step(
        lambda connection, correction: deposit_refund(connection, correction, person, 2_200)
    )
    assert once[0] == "23505" and "settlement_correction_refund_details_once_per_deposit" in str(
        once[1]
    )
    # BR-REFUND-015: the Primary Tenant needs no agreement; another Customer must be a signed
    # Signer even with an agreement.
    stranger = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.customers WHERE id<>%s ORDER BY id LIMIT 1",
                case["customer"],
            )[0]
        )
    )
    assert inside(
        lambda connection, correction: deposit_refund(
            connection, correction, person, 2_200, agreement="All Signers agreed in writing"
        )
    ) == ("23514", "The Primary Tenant needs no Signer agreement")
    assert inside(
        lambda connection, correction: deposit_refund(
            connection,
            correction,
            person,
            2_200,
            recipient=stranger,
            agreement="All Signers agreed in writing",
        )
    ) == (
        "23514",
        "A Refund to another Signer needs a signed Signer and the written agreement of all Signers",
    )

    # The owner's 8r rule: no Refund while a receipt reversal or forfeiture draft for the Deposit
    # waits (written by hand inside the attempt, so it rolls back with it).
    def waiting(connection: psycopg.Connection[Any], correction: UUID) -> None:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'DEPOSIT_FORFEITURE','deposits.dispose',"
            "%s,NULL,%s)",
            (
                prop,
                human,
                uuid4(),
                Jsonb({"variant": "DEPOSIT_RECEIPT_REVERSAL", "deposit_id": str(security)}),
                "Returned transfer",
            ),
        )
        deposit_refund(connection, correction, person, 2_200)

    assert inside(waiting) == (
        "55000",
        "A Deposit receipt reversal or forfeiture draft for this Deposit is waiting",
    )

    # BR-REFUND-014: an active Refund method (deactivated inside the attempt, which rolls back).
    def inactive(connection: psycopg.Connection[Any], correction: UUID) -> None:
        connection.execute(
            "UPDATE app.refund_methods SET active=false,updated_by=%s,"
            "updated_at=statement_timestamp() WHERE id=%s",
            (human, case["cash"]),
        )
        deposit_refund(connection, correction, person, 2_200)

    assert inside(inactive) == ("55000", "Refund Method is not active")
    # A details row naming another Deposit than the Refund's is refused at once, and a Credit
    # Refund whose details name a Deposit is refused at commit (review round 1).
    assert inside(
        lambda connection, correction: refund_rows(
            connection, correction, case["pet"], source_deposit=security
        )
    ) == ("23514", "A post-settlement correction Deposit Refund is written only by its correction")
    assert inside(
        lambda connection, correction: refund_rows(
            connection, correction, security, source_credit=credit
        )
    ) == ("23514", "A post-settlement correction Refund detail names its Refund's own Deposit")
    # A draft whose recorded result no longer matches the real state is stale.
    recorded = {
        key: value
        for key, value in check(url, case, main_plan(case), released_overlay(case)).items()
        if key != "source_revision"
    }
    # The deferred Credit check pins each Credit application to its step, once (review round 1):
    # the 8e-2 writer called twice for the same step is refused at commit.
    two_steps = plan_draft(
        url,
        case,
        plan(credit_step(credit, other_line, 100), credit_step(credit, other_line, 200)),
        released_overlay(case),
        {},
    )

    def same_step_twice(connection: psycopg.Connection[Any]) -> None:
        release(connection, case, two_steps)
        connection.execute(
            "SET CONSTRAINTS "
            "app.settlement_correction_effects_customer_credit_application__fkey DEFERRED"
        )
        for _ in range(2):
            connection.execute(
                "SELECT app.post_final_settlement_credit_application(%s,%s,%s,%s,1)",
                (prop, person, case["settlement"], two_steps),
            )

    assert failure(url, same_step_twice) == (
        "23514",
        "A post-settlement correction Credit application pays exactly the obligation of its "
        "Credit step, once",
    )
    # Every field of the recorded result is compared (review round 1).
    changes: tuple[dict[str, Any], ...] = (
        {"closing_balance_usd_cents": 1},
        {"open_total_usd_cents": 0},
        {"deposit_ids": []},
        {"closing_balances": [{"customer_id": str(case["customer"]), "open_usd_cents": 1}]},
        {"credit_left": {str(credit): 0}},
        {"pet_remainder_chosen_by": "CUSTOMER_ONLY"},
        {"lease_id": str(uuid4())},
        {"termination_ground": "BR-LEASE-005"},
    )
    # The changes cover every recorded field (round-3 hardening, carried into 10c-2a-3).
    assert set().union(*changes) == set(recorded)
    changed_drafts = [
        plan_draft(url, case, main_plan(case), released_overlay(case), {**recorded, **change})
        for change in changes
    ]
    for changed in changed_drafts:

        def stale(connection: psycopg.Connection[Any], changed: UUID = changed) -> None:
            release(connection, case, changed)
            post(connection, case, changed)

        assert failure(url, stale) == ("P5S02", STALE), changed
    assert {state(url, changed) for changed in changed_drafts} == {"PENDING"}
    assert state(url, draft) == "PENDING"
    assert (held(url, security), outstanding(url, other_line)) == (0, 0)


def test_each_customer_s_credit_and_a_refund_to_another_signer_after_closure(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-008, owner answer 1 to Q-2026-10-07-42 and BR-REFUND-015 (review round 1): with
    two Signers, a Customer's Credit pays only that Customer's own debt and must pay it before the
    Pet Deposit does, while the other Signer's Credit is not required because that Signer owes
    nothing; the rest of the Pet Deposit is refunded to the other signed Signer with the written
    agreement of all Signers, kept in the correction's details row."""
    url = migrated_database_url
    case = two_signer_case(url)
    agreement = "All Signers agreed in writing on 2026-10-07 that the Signer receives the Refund"
    pet, tenant_line, co_signer = case["pet"], case["tenant_line"], case["co_signer"]
    confirm(
        case,
        record(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, pet, LINE, tenant_line, 1_500),
                SettlementDepositStep(PET_REST, pet, LINE, case["signer_line"], 600),
                settlement_refund(
                    case,
                    "pet",
                    17_900,
                    recipient_customer_id=co_signer,
                    signer_agreement=agreement,
                ),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    tenant_credit = new_credit(url, case, 200)
    signer_credit = new_credit(url, case, 300, co_signer)
    application = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.deposit_applications WHERE final_settlement_id=%s "
                "AND invoice_line_id=%s",
                case["settlement"],
                tenant_line,
            )[0]
        )
    )
    shape = overlay({f"INVOICE_LINE:{tenant_line}": 500}, {str(pet): 1_500})
    staff = {"basis": "STAFF_REASON", "customer_choice": None, "staff_reason": STAFF_REASON}
    assert plan_refusal(url, case, plan(credit_step(signer_credit, tenant_line, 300)), shape) == (
        "55000",
        "A Customer Credit pays only its own Customer's obligations",
    )
    assert plan_refusal(
        url,
        case,
        plan(
            deposit_step("PET_DEPOSIT_REMAINDER", pet, tenant_line, 500),
            refund_step(
                case,
                pet,
                1_000,
                recipient_customer_id=str(co_signer),
                signer_agreement=agreement,
            ),
            pet_remainder=staff,
        ),
        shape,
    ) == ("55000", CREDIT_FIRST)
    steps = plan(
        credit_step(tenant_credit, tenant_line, 200),
        deposit_step("PET_DEPOSIT_REMAINDER", pet, tenant_line, 300),
        refund_step(
            case, pet, 1_200, recipient_customer_id=str(co_signer), signer_agreement=agreement
        ),
        pet_remainder=staff,
    )
    draft = plan_draft(url, case, steps, shape)
    with psycopg.connect(url) as connection:
        connection.execute(LOCK_PLAN, (draft,))
        correction = begin(connection, case, draft)
        reverse(connection, correction, application, case["person"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        adjust_line(connection, case, tenant_line, adjustment, 1_000)
        written = post(connection, case, draft)
    [refund] = written["refund_ids"]
    assert one(
        url,
        "SELECT refund.recipient_customer_id,refund.source_deposit_id,"
        "refund.usd_accounting_value_cents,detail.signer_agreement,detail.deposit_id "
        "FROM app.refunds refund JOIN app.settlement_correction_refund_details detail "
        "ON detail.refund_id=refund.id WHERE refund.id=%s",
        refund,
    ) == (co_signer, pet, 1_200, agreement, pet)
    assert one(
        url,
        "SELECT application_stage,amount_usd_cents,reason FROM app.deposit_applications "
        "WHERE id=%s",
        written["deposit_application_ids"][0],
    ) == ("PET_REMAINDER_EXPLICIT", 300, STAFF_REASON)
    assert (held(url, pet), outstanding(url, tenant_line)) == (0, 0)
    assert one(
        url,
        "SELECT app.credit_available_value(%s),app.credit_available_value(%s)",
        tenant_credit,
        signer_credit,
    ) == (0, 300)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["tenant"])
        assert_reconciled(connection, co_signer)


def test_a_late_payment_charge_target_and_another_settlement_s_correction(
    migrated_database_url: str,
) -> None:
    """DL-032, BR-SETTLE-013 and BR-AUTH-010 (review round 1): the step pays a Late-payment Charge
    with Customer Credit first and then with the Pet Deposit (pet damage first, then the rest by
    the staff step), after the correction gives the Pet Deposit the Charge's amount back; and a
    Credit application, a Deposit application or a Deposit Refund of one Settlement linked to a
    correction of another Settlement is refused."""
    url = migrated_database_url
    other = closed_case(url)
    case = reversal_case(url)
    case["cash"] = UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0]))
    pet, charge, pet_line = case["pet"], case["charge"], case["pet_line"]
    charge_due, paid = case["charge_due"], case["charge_paid"]
    assert charge_due > 300
    # A Customer who owes gets no Credit from a Payment's excess (the existing excess rule); the
    # Credit here is the value the correction's own credit Adjustment releases from a Payment of
    # the other line made after closure (BR-CREDIT-014; full run P3, cause C).
    other_line, other_invoice_b = case["other_line"], invoice_of(url, case["other_line"])
    other_due = outstanding(url, other_line)
    assert other_due > 300
    pay(url, case["prop"], case["human"], case["customer"], other_invoice_b, other_line, other_due)
    allocation = UUID(
        str(
            one(
                url,
                "SELECT allocation.id FROM app.payment_allocations allocation "
                "WHERE allocation.invoice_id=%s AND NOT EXISTS(SELECT 1 FROM "
                "app.payment_allocation_reversals reversal "
                "WHERE reversal.payment_allocation_id=allocation.id)",
                other_invoice_b,
            )[0]
        )
    )
    pool = held(url, pet) + paid
    steps: list[dict[str, Any]] = [credit_step(allocation, charge, 300, "LATE_PAYMENT_CHARGE")]
    damage = min(outstanding(url, pet_line), pool)
    if damage:
        steps.append(deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, damage))
        pool -= damage
    on_charge = 0
    for target, owed, kind in (
        (charge, charge_due - 300, "LATE_PAYMENT_CHARGE"),
        (case["other_line"], outstanding(url, case["other_line"]), "INVOICE_LINE"),
        (case["rent_line"], outstanding(url, case["rent_line"]), "INVOICE_LINE"),
    ):
        amount = min(pool, owed)
        if amount > 0:
            steps.append(deposit_step("PET_DEPOSIT_REMAINDER", pet, target, amount, kind))
            pool -= amount
            on_charge = amount if target == charge else on_charge
    if pool > 0:
        steps.append(refund_step(case, pet, pool))
    # The fixture's amounts give both a pet damage step and a Pet Deposit step on the Charge
    # (review round 2).
    assert damage > 0 and on_charge > 0
    staff = {"basis": "STAFF_REASON", "customer_choice": None, "staff_reason": STAFF_REASON}
    shape = overlay(
        {f"LATE_PAYMENT_CHARGE:{charge}": charge_due},
        {str(pet): paid},
        {
            str(allocation): {
                "customer_id": str(case["customer"]),
                "add_usd_cents": 300,
                "released_payment_allocation_id": str(allocation),
            }
        },
    )
    draft = plan_draft(url, case, plan(*steps, pet_remainder=staff), shape)
    with psycopg.connect(url) as connection:
        connection.execute(LOCK_PLAN, (draft,))
        correction = begin(connection, case, draft)
        reverse(connection, correction, case["charge_application"], case["person"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        adjust_line(connection, case, other_line, adjustment, 300)
        written = post(connection, case, draft)
    assert held(url, pet) == 0
    assert (charge_remaining(url, charge), outstanding(url, other_line)) == (
        charge_due - 300 - on_charge,
        0,
    )
    assert one(
        url,
        "SELECT target_kind,late_payment_charge_id,within_invoice_basis,amount_usd_cents,"
        "customer_credit_id FROM app.customer_credit_applications WHERE id=%s",
        written["credit_application_ids"][0],
    ) == (
        "LATE_PAYMENT_CHARGE",
        charge,
        "NOT_APPLICABLE",
        300,
        UUID(written["credit_ids"][str(allocation)]),
    )
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_applications application "
        "JOIN app.settlement_correction_effects effect "
        "ON effect.deposit_application_id=application.id "
        "WHERE effect.settlement_correction_id=%s AND application.late_payment_charge_id=%s",
        correction,
        charge,
    ) == (1 if on_charge else 0,)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])
    # Records of Settlement A linked to a correction of Settlement B stay refused.
    other_invoice = invoice_of(url, other["other_line"])

    def credit_of_a(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, case["draft"])
        application = uuid4()
        connection.execute(LINK, (correction, "customer_credit_application_id", application))
        connection.execute(
            "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,"
            "invoice_id,final_settlement_id,amount_usd_cents,within_invoice_basis,occurred_at,"
            "actor_id,authorization_reference) VALUES (%s,%s,'INVOICE',%s,%s,300,"
            "'OTHER_APPLICABLE_OBLIGATION',clock_timestamp(),%s,'financial.approve')",
            (
                application,
                other["new_credit"],
                other_invoice,
                other["settlement"],
                case["person"],
            ),
        )

    def deposit_of_a(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, case["draft"])
        application = uuid4()
        connection.execute(LINK, (correction, "deposit_application_id", application))
        connection.execute(
            "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,'SECURITY_EXPLICIT',"
            "'INVOICE_LINE',%s,100,9,%s)",
            (
                other["prop"],
                case["person"],
                other["settlement"],
                application,
                other["security"],
                other["other_line"],
                REASON,
            ),
        )

    def refund_of_a(connection: psycopg.Connection[Any]) -> None:
        correction = begin(connection, case, case["draft"])
        connection.execute(
            REFUND_WRITER,
            (
                case["prop"],
                case["person"],
                correction,
                case["draft"],
                other["security"],
                100,
                other["customer"],
                case["cash"],
                NOTE,
                None,
                REASON,
            ),
        )

    assert failure(url, credit_of_a) == ("55000", CLOSED_CREDIT)
    assert failure(url, deposit_of_a) == ("55000", CLOSED_DEPOSIT)
    assert failure(url, refund_of_a) == (
        "23514",
        "The Refund source must be a Deposit of the terminated Settlement Lease",
    )
    assert (state(url, case["draft"]), state(url, draft)) == ("PENDING", "CONFIRMED")


def test_an_inspection_correction_waits_for_the_step_and_its_line_is_then_no_pet_damage(
    migrated_database_url: str,
) -> None:
    """DL-032 step 3 and the owner answer to Q-2026-10-07-43 (review round 2): the
    step locks the Lease row FOR UPDATE, as the move-out inspection command that supersedes an
    inspection does, so that command waits while a correction pays a pet damage line from the
    Pet Deposit.

    Changed in sub-slice 10c-2a-4 (owner exception, owner answer to Q-2026-10-08-50): the name's
    last words ("its line is then no pet damage") describe the behaviour before 10c-2a-4, when the
    waiting supersede was written after the step and the line stopped being pet damage. Since
    10c-2a-4 a supersede on a Lease whose Final Settlement is closed is refused (owner answer to
    Q-2026-10-08-49), and the command reads the closure only after the Lease row lock, so the wait
    still matters: the command waits for the step's lock, is then refused (P5S01) and writes
    nothing; the line stays pet damage and the Pet Deposit pays it as pet damage."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, lease = case["prop"], case["human"], case["lease"]
    pet, pet_line = case["pet"], case["pet_line"]
    pet_first = pet_first_application(url, case)
    # The correction gives the Pet Deposit the 12,500 it paid back and removes 4,000 of the line;
    # the Customer's Credit pays first, the Pet Deposit pays the rest as pet damage.
    steps = plan(
        credit_step(case["new_credit"], pet_line, 300),
        deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, 8_200),
        refund_step(case, pet, 4_300),
    )
    draft = plan_draft(
        url, case, steps, overlay({f"INVOICE_LINE:{pet_line}": 8_500}, {str(pet): 12_500})
    )
    earlier = UUID(
        str(one(url, "SELECT id FROM app.move_out_inspections WHERE lease_id=%s", lease)[0])
    )
    version = int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0]))
    superseding = RecordMoveOutInspection(
        uuid4(),
        uuid4(),
        version,
        today(url),
        "Corrected inspection condition",
        "Approved inspection",
        "Evidence-903",
        "The door was scratched before the pet moved in",
        (InspectionFinding(uuid4(), "Scratched door, not caused by the pet", False),),
        supersedes_inspection_id=earlier,
    )
    application_name = f"v1056-inspection-lock-{uuid4().hex}"
    inspections = PostgresMoveOutInspectionService(
        runtime_database_url(),
        make_conninfo(financial_database_url(), application_name=application_name),
    )
    with psycopg.connect(url) as holding:
        release_line(holding, case, draft, (pet_first,), pet_line, 4_000)
        written = post(holding, case, draft)
        assert len(written["deposit_application_ids"]) == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                inspections.record,
                prop,
                lease,
                superseding,
                actor=inspection_actor(human, prop),
                request_id="settlement-correction-inspection",
            )
            try:
                # Since 10c-2a-4 (review round 1): the wait is on the Lease row itself, not on
                # the Settlement row the step also holds.
                assert blocked_on_lease_row(application_name, holding), (
                    "The inspection correction must wait on the step's Lease lock"
                )
            finally:
                holding.rollback()
            # Changed in 10c-2a-4 (owner answer to Q-2026-10-08-50): the waiting supersede now
            # reads the closed Settlement after the lock and is refused (was: written).
            with pytest.raises(MoveOutInspectionConflictError) as refused:
                future.result(timeout=10)
    error = refused.value.__cause__
    assert isinstance(error, psycopg.Error)
    assert (error.sqlstate, error.diag.message_primary) == ("P5S01", SUPERSEDE_CLOSED)
    assert (
        int(
            str(
                one(
                    url,
                    "SELECT count(*) FROM app.move_out_inspections WHERE lease_id=%s OR id=%s",
                    lease,
                    superseding.inspection_id,
                )[0]
            )
        )
        == 1
    )
    assert state(url, draft) == "PENDING"
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 0)
    # Changed in 10c-2a-4: the line stays pet damage (was: False after the supersede).
    assert one(url, "SELECT app.invoice_line_is_pet_damage(%s,%s)", pet_line, lease) == (True,)

    # Changed in 10c-2a-4: the step pays the line from the Pet Deposit as pet damage (was: refused
    # with PET_DAMAGE_ONLY). The step's own re-check of pet damage stays as a second guard; the
    # deferred checks run as a commit would, and the transaction then rolls back.
    with psycopg.connect(url) as connection:
        try:
            release_line(connection, case, draft, (pet_first,), pet_line, 4_000)
            paid = post(connection, case, draft)
            assert [
                tuple(row)
                for row in connection.execute(
                    "SELECT deposit_id,invoice_line_id,amount_usd_cents,application_stage "
                    "FROM app.deposit_applications WHERE id=ANY(%s)",
                    ([UUID(str(item)) for item in paid["deposit_application_ids"]],),
                ).fetchall()
            ] == [(pet, pet_line, 8_200, "PET_RELATED_FIRST")]
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            connection.rollback()
    assert state(url, draft) == "PENDING"
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 0)


def test_a_br_dep_027_termination_after_closure(migrated_database_url: str) -> None:
    """BR-DEP-027 and BR-LEASE-005 (review round 2): at an unpaid-Initial termination the
    remaining Pet Deposit pays other debt only by the Customer's choice, so a staff reason is
    refused; with the Customer's choice the step writes it, and the Pet Deposit's rest is refunded
    while other debt stays open, which the plan check and the correction's Deposit Refund source
    check both accept. The Security Deposit is kept and holds nothing."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human = case["prop"], case["human"]
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human), case["security"]
    )
    confirm(
        case,
        record(
            case,
            (
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
                settlement_refund(case, "pet", 5_500),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    pet_first = pet_first_application(url, case)
    assert (held(url, pet), held(url, case["security"]), outstanding(url, other_line)) == (
        0,
        0,
        10_500,
    )
    shape = overlay({f"INVOICE_LINE:{pet_line}": 8_500}, {str(pet): 12_500})
    # Sub-slice 10c-2a-6 (owner answer to Q-2026-10-08-54): the step refuses the Final
    # Settlement's own choice text, so this correction carries a choice given for it.
    choice = {
        "basis": "CUSTOMER_CHOICE",
        "customer_choice": "Primary Tenant, 2026-10-08, signed note for this correction",
        "staff_reason": CHOICE.staff_reason,
    }
    staff = {"basis": "STAFF_REASON", "customer_choice": None, "staff_reason": STAFF_REASON}

    def steps(pet_remainder: dict[str, Any]) -> dict[str, Any]:
        return plan(
            deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, 8_500),
            deposit_step("PET_DEPOSIT_REMAINDER", pet, other_line, 2_000),
            refund_step(case, pet, 2_000),
            pet_remainder=pet_remainder,
        )

    assert plan_refusal(url, case, steps(staff), shape) == ("55000", CUSTOMER_ONLY)
    result = check(url, case, steps(choice), shape)
    assert result["pet_remainder_chosen_by"] == "CUSTOMER_ONLY"
    assert result["closing_balance_usd_cents"] == result["open_total_usd_cents"] - 10_500 > 0
    draft = plan_draft(url, case, steps(choice), shape)
    with psycopg.connect(url) as connection:
        release_line(connection, case, draft, (pet_first,), pet_line, 4_000)
        written = post(connection, case, draft)
    assert state(url, draft) == "CONFIRMED"
    assert written["closing_balance_usd_cents"] == result["closing_balance_usd_cents"]
    assert [
        one(
            url,
            "SELECT application_stage,target_kind,invoice_line_id,amount_usd_cents,reason "
            "FROM app.deposit_applications WHERE id=%s",
            application,
        )
        for application in written["deposit_application_ids"]
    ] == [
        ("PET_RELATED_FIRST", "INVOICE_LINE", pet_line, 8_500, REASON),
        ("PET_REMAINDER_EXPLICIT", "INVOICE_LINE", other_line, 2_000, CHOICE.staff_reason),
    ]
    [refund] = written["refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,usd_accounting_value_cents,recipient_customer_id "
        "FROM app.refunds WHERE id=%s",
        refund,
    ) == (pet, 2_000, case["customer"])
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (
        0,
        0,
        8_500,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_credit_after_closure_follows_the_rent_first_proposal_or_the_designation(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29; review round 2): a correction's Credit
    step on an Invoice with Rent or Service lines follows the Rent-first proposal unless the
    Customer designated the line; the step's Credit applications record the designation or the
    proposal, as the correction's Credit check requires. Here the correction reverses the
    Settlement's Credit applications, so the Customer's Credit gets the value back and pays the
    Invoice again."""
    url = migrated_database_url
    case = mixed_rent_case(url)
    credit, customer = case["credit"], case["customer"]
    (rent, _), (trash, _), (internet, _) = case["lines"]
    owed = {line: outstanding(url, line) for line, _ in case["lines"]}
    confirm(
        case,
        record(
            case,
            tuple(
                SettlementCreditStep(credit, LINE, line, owed[line])
                for line in (rent, trash, internet)
            ),
        ),
    )
    case["person"] = approver(url)
    with psycopg.connect(url) as connection:
        applications = [
            UUID(str(row[0]))
            for row in connection.execute(
                "SELECT id FROM app.customer_credit_applications WHERE final_settlement_id=%s",
                (case["settlement"],),
            ).fetchall()
        ]
    assert len(applications) == 3 and sum(owed[line] for line in owed) > 0
    shape = overlay(
        {f"INVOICE_LINE:{line}": owed[line] for line in owed},
        credits={
            str(credit): {
                "customer_id": str(customer),
                "add_usd_cents": sum(owed.values()),
                "released_payment_allocation_id": None,
            }
        },
    )
    for order in ((trash, rent, internet), (rent, internet, trash)):
        assert plan_refusal(
            url, case, plan(*(credit_step(credit, line, owed[line]) for line in order)), shape
        ) == ("55000", RENT_FIRST)
    designation = (
        "Primary Tenant asked on 2026-10-07, by signed note, to clear the Service line first"
    )
    steps = plan(
        {**credit_step(credit, internet, owed[internet]), "customer_designation": designation},
        credit_step(credit, rent, owed[rent]),
        credit_step(credit, trash, owed[trash]),
    )
    draft = plan_draft(url, case, steps, shape)
    with psycopg.connect(url) as connection:
        connection.execute(LOCK_PLAN, (draft,))
        correction = begin(connection, case, draft)
        for application in applications:
            reversal = uuid4()
            connection.execute(LINK, (correction, "credit_application_reversal_id", reversal))
            connection.execute(CREDIT_REVERSAL, (reversal, application, REASON, case["human"]))
        written = post(connection, case, draft)
    assert state(url, draft) == "CONFIRMED"
    assert [
        one(
            url,
            "SELECT application.within_invoice_basis,application.customer_designation_reference,"
            "detail.invoice_line_id,detail.attribution_basis "
            "FROM app.customer_credit_applications application "
            "JOIN app.customer_credit_application_details detail "
            "ON detail.customer_credit_application_id=application.id WHERE application.id=%s",
            application,
        )
        for application in written["credit_application_ids"]
    ] == [
        ("CUSTOMER_DESIGNATED", designation, internet, "CUSTOMER_DESIGNATED"),
        ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", None, rent, "RENT_FIRST_PROPOSAL"),
        ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", None, trash, "SERVICE_PROPOSAL"),
    ]
    assert [outstanding(url, line) for line in owed] == [0, 0, 0]
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_the_settlement_correction_step_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in INTERNAL:
            definer, settings = cast(
                tuple[bool, list[str] | None],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert settings is not None and "search_path=pg_catalog" in settings, function
            # Only the pure amount check runs with the caller's rights.
            assert definer is (function != INTERNAL[0]), function
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
            # BR-SETTLE-013, no time limit: the intervals bound the clock or order events.
            source = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (function,)
            ).fetchone()
            # The function age() is not called (a name such as is_pet_damage( is not a call of it).
            assert source is not None, function
            assert re.search(r"(?<![a-z_])age\(", str(source[0])) is None, function
            assert set(re.findall(r"interval '([^']*)'", str(source[0]))) <= {
                "5 seconds",
                "1 microsecond",
            }
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.settlement_correction_refund_details',"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                (role,),
            ).fetchone() == (False,), role
        # The two new columns: nullable, the Deposit key and the 8d agreement limits.
        assert connection.execute(
            "SELECT array_agg(attname::text ORDER BY attnum) FROM pg_catalog.pg_attribute "
            "WHERE attrelid='app.settlement_correction_refund_details'::regclass AND attnum>0 "
            "AND NOT attisdropped AND NOT attnotnull"
        ).fetchone() == (["deposit_id", "signer_agreement"],)
        assert connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='settlement_correction_refund_details_agreement_deposit'"
        ).fetchone() == ("CHECK (((signer_agreement IS NULL) OR (deposit_id IS NOT NULL)))",)
        # Each Deposit at most once per correction (review round 1).
        assert connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='settlement_correction_refund_details_once_per_deposit'"
        ).fetchone() == ("UNIQUE (settlement_correction_id, deposit_id)",)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261106_102")
    assert revision is not None and revision.down_revision == "20261105_101"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
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

    with _temporary_migration_database("settlement_correction_plan") as temporary:
        alembic_command.upgrade(config, "20261105_101")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261106_102")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    # Only the seven relaxed or extended checks and writers change; each names this sub-slice.
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for name in CHANGED:
        assert "10c-2a-2" in str(after_functions[name]), name
        assert "10c-2a-2" not in str(before_functions[name]), name
