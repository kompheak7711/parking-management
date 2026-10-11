"""Pay back returned Pet Refund-review money after a pet noncompliance termination (V1-056
sub-slice 10c-2b-5).

Owner answer pay back to Q-2026-10-09-61, answer (a) to Q-2026-10-10-73, answers (A) and (b) to
Q-2026-10-10-75 and answer (a) to Q-2026-10-10-76: money of a Pet Refund-review Refund (DL-053)
that comes back is the Customer's, whenever it came back; its amount is a running count (a return
adds, a return reversal and every later Pet Refund-review Refund take out first), never more than
the Pet Deposit holds. A Pet Deposit whose held money is all pay-back money follows DL-032 before
and after closure (BR-SETTLE-008); a forfeiture (BR-DEP-022) takes only the money beyond it.
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

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from lease_deposit_forfeiture_test_support import forfeit_through_draft, record_disposition_as_owner
from property_rental.deposit import (
    CreatePetDepositCommand,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositDispositionCommand,
    RecordPetDepartureCommand,
)
from property_rental.final_settlement import FinalSettlementConflictError, SettlementDepositStep
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureInvalidError
from property_rental.refund import ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled
from test_deposit_migration import deposit_actor, seed_historical_deposit_receipt
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, start
from test_final_settlement_preview_migration import deposit_of, pay, preview
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_pet_refund_migration import command as pet_command
from test_refund_service_migration import corrections, refund_id, returned
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_return_migration import confirm, net, record, return_command
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261123_119"
INTERNAL = (
    "app.lease_deposit_payback_count(uuid)",
    "app.lease_deposit_payback_value(uuid)",
    "app.lease_deposit_payback_after_return(uuid,uuid,bigint)",
)
CHANGED = {
    "app.lease_deposit_settlement_path(uuid,uuid)": "PATH_REPLACEMENTS",
    "app.lease_deposit_forfeiture_source(uuid,uuid)": "FORFEITURE_SOURCE_REPLACEMENTS",
    "app.settlement_refund_return_plan(uuid,uuid,jsonb)": "RETURN_PLAN_REPLACEMENTS",
}
NOTHING_TO_FORFEIT = ("22023", "The Deposit holds nothing to forfeit")
PATH = "SELECT app.lease_deposit_settlement_path(%s,%s)"


def pet_case(
    url: str, history: tuple[tuple[str, int], ...], *, pet_amount: int = 20_000, debt: int = 0
) -> dict[str, Any]:
    """A signed Lease starting this month with its Security Deposit and a Pet Deposit of
    pet_amount, received in full. The pet leaves and a DL-053 review qualifies. While the Lease is
    signed, each history step runs in order: ("refund", n) pays a Pet Refund-review Refund of n,
    ("return", n) verifies a one-call return of n of the latest one, ("reverse", 0) reverses the
    latest return. The Initial Rent is paid except debt; the Lease is terminated for pet
    noncompliance after three warnings (BR-DEP-022). Nothing is forfeited yet."""
    source = signed_with_initial(url, this_month(url))
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Synthetic approved pet',clock_timestamp(),%s)",
            (approval, lease, day, human),
        )
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    who = deposit_actor(human, prop)
    pet = uuid4()
    deposits.create_pet_deposit(
        CreatePetDepositCommand(
            uuid4(), pet, lease, approval, pet_amount, day, "Approved signed Lease pet terms"
        ),
        actor=who,
    )
    seed_historical_deposit_receipt(
        url, deposit_id=pet, actor_id=human, amount_usd_cents=pet_amount
    )
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), pet, day, "Pet permanently left")
    deposits.record_pet_departure(departure, actor=who)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        pet,
        30000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=who)
    latest_refund: UUID | None = None
    latest_return: UUID | None = None
    for kind, amount in history:
        if kind == "refund":
            latest_refund = refund_id(
                create_pet_refund(
                    refunds(),
                    prop,
                    pet_command(pet, review.review_id, amount),
                    actor=refund_actor(human, prop, "refunds.create"),
                )
            )
        elif kind == "return":
            assert latest_refund is not None
            [row] = corrections(
                refunds().verify_usd_return(
                    prop,
                    latest_refund,
                    returned(amount),
                    actor=refund_actor(human, prop, "refunds.correct"),
                )
            )
            latest_return = UUID(str(row["id"]))
        else:
            assert latest_refund is not None and latest_return is not None
            refunds().reverse_correction(
                prop,
                latest_refund,
                latest_return,
                ReverseRefundCorrectionCommand(
                    uuid4(), "Bank recall slip", "The return was a mistake"
                ),
                actor=refund_actor(human, prop, "refunds.corrections.reverse"),
            )
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed - debt)
    terminate_for_disposition(url, deposits, lease, day)
    return {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "rent": rent,
        "day": day,
        "deposits": deposits,
        "review_refund": latest_refund,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }


def path(case: dict[str, Any], deposit: str) -> tuple[str, int]:
    found = one(case["url"], PATH, case["prop"], case[deposit])[0]
    return found["path"], found["payback_usd_cents"]


def forfeited(case: dict[str, Any], deposit: str) -> list[int]:
    with psycopg.connect(case["url"]) as connection:
        return [
            int(row[0])
            for row in connection.execute(
                "SELECT amount_usd_cents FROM app.deposit_dispositions WHERE deposit_id=%s "
                "ORDER BY occurred_at,id",
                (case[deposit],),
            ).fetchall()
        ]


def forfeit(case: dict[str, Any], deposit: str) -> None:
    forfeit_through_draft(case["deposits"], case[deposit])


def after_return(case: dict[str, Any], deposit: str, refund: object, amount: int | None) -> bool:
    """The returned-Refund plan's pay-back exception, called as the owner."""
    return bool(
        one(
            case["url"],
            "SELECT app.lease_deposit_payback_after_return(%s,%s,%s)",
            case[deposit],
            refund,
            amount,
        )[0]
    )


def refused_forfeiture(case: dict[str, Any], deposit: str) -> tuple[Any, Any]:
    with pytest.raises(LeaseDepositForfeitureInvalidError) as failure:
        forfeit(case, deposit)
    return cause(failure)


@pytest.mark.parametrize(
    ("history", "payback", "pet_forfeited", "after"),
    [
        # The Q-2026-10-10-76 example: $500 Pet Deposit, a $300 Refund returned and paid again.
        ((("refund", 30_000), ("return", 30_000), ("refund", 30_000)), 0, 20_000, ("KEPT", 0)),
        # The same with a $100 second Refund: $200 paid back, $200 forfeited.
        (
            (("refund", 30_000), ("return", 30_000), ("refund", 10_000)),
            20_000,
            20_000,
            ("DL_032", 20_000),
        ),
        # A reversal of the return takes the returned money out first.
        ((("refund", 30_000), ("return", 30_000), ("reverse", 0)), 0, 20_000, ("KEPT", 0)),
    ],
    ids=["paid-again", "smaller-second-refund", "return-reversed"],
)
def test_the_payback_value_is_a_running_count(
    migrated_database_url: str,
    history: tuple[tuple[str, int], ...],
    payback: int,
    pet_forfeited: int,
    after: tuple[str, int],
) -> None:
    """Owner answer (a) to Q-2026-10-10-76 on a 50,000 Pet Deposit: after the termination the Pet
    Deposit's pay-back value follows the running count, its forfeiture takes exactly the money
    beyond it, and what is left afterwards is all pay-back money (DL-032) or nothing (kept). The
    Security Deposit has no pay-back value and is forfeited whole."""
    url = migrated_database_url
    case = pet_case(url, history, pet_amount=50_000)
    security = held(url, case["security"])
    assert security > 0
    assert path(case, "security") == ("FORFEITURE_REQUIRED", 0)
    assert path(case, "pet") == ("FORFEITURE_REQUIRED", payback)
    assert held(url, case["pet"]) == pet_forfeited + payback
    forfeit(case, "security")
    forfeit(case, "pet")
    assert (forfeited(case, "security"), forfeited(case, "pet")) == ([security], [pet_forfeited])
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, payback)
    assert path(case, "pet") == after
    # Nothing beyond the pay-back money is left, so a second forfeiture is refused.
    assert refused_forfeiture(case, "pet") == NOTHING_TO_FORFEIT


@pytest.mark.parametrize("debt", [0, 1_000], ids=["no-debt", "open-debt"])
def test_returned_money_alone_pays_the_debt_and_is_refunded_by_the_final_settlement(
    migrated_database_url: str, debt: int
) -> None:
    """Q-2026-10-10-75 (A): the whole 20,000 Pet Deposit was refunded while the Lease was signed;
    after the pet noncompliance termination 5,000 comes back. The Pet Deposit is on the DL-032 path
    with 5,000 of pay-back money (the preview shows it), so its forfeiture is refused and a
    Settlement that leaves it unused is refused (BR-SETTLE-008); the Settlement applies it to the
    unpaid Rent first (1,000, or nothing with no debt) and refunds the rest to the Customer."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 20_000),), debt=debt)
    assert path(case, "pet") == ("NOTHING_HELD", 0)
    refunds().verify_usd_return(
        case["prop"],
        case["review_refund"],
        returned(5_000),
        actor=refund_actor(case["human"], case["prop"], "refunds.correct"),
    )
    assert (held(url, case["pet"]), path(case, "pet")) == (5_000, ("DL_032", 5_000))
    item = deposit_of(preview(case["prop"], case["human"], case["settlement"]), case["pet"])
    assert (item["path"], item["payback_usd_cents"], item["held_usd_cents"]) == (
        "DL_032",
        5_000,
        5_000,
    )
    assert refused_forfeiture(case, "pet") == NOTHING_TO_FORFEIT
    assert forfeited(case, "pet") == []
    forfeit(case, "security")
    with pytest.raises(FinalSettlementConflictError) as unused:
        record_settlement(case, ())
    assert cause(unused) == ("55000", "Every remaining Deposit balance must be applied or refunded")
    rest = settlement_refund(case, "pet", 5_000 - debt)
    if debt:
        steps = (SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent"], debt), rest)
        draft = record_settlement(case, steps, pet_remainder=STAFF)
    else:
        draft = record_settlement(case, (rest,))
    confirm_settlement(case, draft)
    assert (outstanding(url, case["rent"]), held(url, case["pet"])) == (0, 0)
    assert one(
        url,
        "SELECT refund.usd_accounting_value_cents,refund.recipient_customer_id "
        "FROM app.final_settlement_refund_details detail "
        "JOIN app.refunds refund ON refund.id=detail.refund_id "
        "WHERE detail.final_settlement_id=%s AND detail.deposit_id=%s",
        case["settlement"],
        case["pet"],
    ) == (5_000 - debt, case["customer"])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_forfeiture_leaves_money_returned_before_the_termination_for_the_settlement(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-10-75 (b) and Q-2026-10-10-73 (a): 15,000 of the 20,000 Pet Deposit was refunded
    and 3,000 of it came back before the termination, so the Pet Deposit holds 8,000: 5,000 of its
    own and 3,000 of pay-back money. The forfeiture takes 5,000; the kept Pet Deposit then follows
    DL-032 for the 3,000, which pays the 1,000 of unpaid Rent and refunds 2,000; a second
    forfeiture is refused, so the 10d guard on another active forfeiture is not reached."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000), ("return", 3_000)), debt=1_000)
    assert (held(url, case["pet"]), path(case, "pet")) == (8_000, ("FORFEITURE_REQUIRED", 3_000))
    forfeit(case, "security")
    forfeit(case, "pet")
    assert forfeited(case, "pet") == [5_000]
    assert (held(url, case["pet"]), path(case, "pet")) == (3_000, ("DL_032", 3_000))
    assert refused_forfeiture(case, "pet") == NOTHING_TO_FORFEIT
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent"], 1_000),
                settlement_refund(case, "pet", 2_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    assert (outstanding(url, case["rent"]), held(url, case["pet"])) == (0, 0)
    assert forfeited(case, "pet") == [5_000]
    assert path(case, "pet") == ("KEPT", 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_after_closure_returned_money_first_pays_the_open_debt(migrated_database_url: str) -> None:
    """Q-2026-10-10-75 (A) after closure: the whole Pet Deposit was refunded while the Lease was
    signed, so the Settlement closes with 1,000 of Rent unpaid and nothing to apply. A return of
    5,000 with a new Refund pays the 1,000 first and refunds 4,000; a return-only correction of
    2,000 more leaves pay-back money held on the DL-032 path, and a held-value Refund pays it back.
    The Settlement row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 20_000),), debt=1_000)
    forfeit(case, "security")
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    before = settlement_row(url, case["settlement"])
    assert (outstanding(url, case["rent"]), path(case, "pet")) == (1_000, ("NOTHING_HELD", 0))
    review_refund = case["review_refund"]
    assert after_return(case, "pet", review_refund, 5_000) is True
    paid_back = confirm(
        case,
        record(
            case,
            return_command(
                case,
                review_refund,
                5_000,
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent"], 1_000),
                settlement_refund(case, "pet", 4_000),
                pet_remainder=STAFF,
            ),
        ),
    )
    [applied] = paid_back["deposit_applications"]
    assert (applied["deposit_id"], applied["amount_usd_cents"]) == (str(case["pet"]), 1_000)
    [paid] = paid_back["refunds"]
    assert (paid["source_deposit_id"], paid["recipient_customer_id"], paid["amount_usd_cents"]) == (
        str(case["pet"]),
        str(case["customer"]),
        4_000,
    )
    assert (outstanding(url, case["rent"]), held(url, case["pet"])) == (0, 0)
    assert net(url, review_refund) == 15_000
    earlier = return_only(case, review_refund, 2_000)
    assert (held(url, case["pet"]), path(case, "pet")) == (2_000, ("DL_032", 2_000))
    held_back = confirm_held(
        case, record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 2_000)))
    )
    [again] = held_back["refunds"]
    assert (again["source_deposit_id"], again["amount_usd_cents"]) == (str(case["pet"]), 2_000)
    assert held(url, case["pet"]) == 0
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_after_closure_a_kept_pet_deposit_pays_returned_money_to_the_open_debt_first(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-10-75 (A) for a kept Pet Deposit after closure: 15,000 of the 20,000 Pet Deposit
    was refunded while the Lease was signed; the forfeiture takes the 5,000 held, so the Pet
    Deposit is kept and empty, and the Settlement closes with 1,000 of Rent unpaid. After closure
    3,000 comes back with a new Refund: although the forfeiture stays active, the 3,000 is pay-back
    money on the DL-032 path; it pays the 1,000 first and refunds 2,000; the forfeiture and the
    Settlement row are unchanged."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000),), debt=1_000)
    forfeit(case, "security")
    forfeit(case, "pet")
    assert (forfeited(case, "pet"), held(url, case["pet"])) == ([5_000], 0)
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    before = settlement_row(url, case["settlement"])
    assert (outstanding(url, case["rent"]), path(case, "pet")) == (1_000, ("KEPT", 0))
    paid_back = confirm(
        case,
        record(
            case,
            return_command(
                case,
                case["review_refund"],
                3_000,
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent"], 1_000),
                settlement_refund(case, "pet", 2_000),
                pet_remainder=STAFF,
            ),
        ),
    )
    [applied] = paid_back["deposit_applications"]
    assert (applied["deposit_id"], applied["amount_usd_cents"]) == (str(case["pet"]), 1_000)
    [paid] = paid_back["refunds"]
    assert (paid["source_deposit_id"], paid["recipient_customer_id"], paid["amount_usd_cents"]) == (
        str(case["pet"]),
        str(case["customer"]),
        2_000,
    )
    assert (outstanding(url, case["rent"]), held(url, case["pet"])) == (0, 0)
    assert (forfeited(case, "pet"), path(case, "pet")) == ([5_000], ("KEPT", 0))
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_kept_pet_deposit_holding_its_own_money_is_not_paid_back(
    migrated_database_url: str,
) -> None:
    """The refusing side of the pay-back exception, on a state no forfeiture draft reaches: 15,000
    of the 20,000 Pet Deposit was refunded and 3,000 came back before the termination (8,000 held,
    3,000 of it pay-back money); the owner's one-call disposition forfeits only 4,000, so the kept
    Pet Deposit holds 1,000 of its own money with the 3,000 (KEPT). After closure a return of 1,000
    more with a new Refund is refused (55000, only on the DL-032 path) and no draft is recorded; a
    return-only correction is accepted and a held-value Refund of its money is refused the same
    way. The exception is false for a returned amount of 0 or none and for a Security Deposit."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000), ("return", 3_000)))
    forfeit(case, "security")
    record_disposition_as_owner(
        case["deposits"],
        RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            case["pet"],
            case["lease"],
            4_000,
            case["day"],
            "Approved BR-DEP-022 source",
            context=disposition_context(url, case["pet"]),
        ),
        actor=deposit_actor(case["human"], case["prop"]),
    )
    assert (held(url, case["pet"]), path(case, "pet")) == (4_000, ("KEPT", 3_000))
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    review_refund = case["review_refund"]
    drafts = (
        "SELECT count(*) FROM app.financial_drafts WHERE kind='SETTLEMENT_CORRECTION' "
        "AND payload->>'final_settlement_id'=%s"
    )
    only_dl032 = (
        "55000",
        "A returned Deposit pays debt or is refunded again only on the DL-032 path",
    )
    assert after_return(case, "pet", review_refund, 1_000) is False
    with pytest.raises(FinalSettlementConflictError) as refunded:
        record(
            case,
            return_command(case, review_refund, 1_000, settlement_refund(case, "pet", 1_000)),
        )
    assert cause(refunded) == only_dl032
    assert one(url, drafts, str(case["settlement"])) == (0,)
    earlier = return_only(case, review_refund, 1_000)
    assert (held(url, case["pet"]), path(case, "pet")) == (5_000, ("KEPT", 4_000))
    with pytest.raises(FinalSettlementConflictError) as held_back:
        record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    assert cause(held_back) == only_dl032
    assert one(url, drafts, str(case["settlement"])) == (1,)
    for amount in (0, None):
        assert after_return(case, "pet", review_refund, amount) is False
    assert after_return(case, "security", review_refund, 1_000) is False
    assert held(url, case["pet"]) == 5_000
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_payback_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the three new internal functions (their only privilege entry is the
    owner's); the migration adds only them and patches the Deposit path, the forfeiture source and
    the returned-Refund plan, each new body exactly the old one with its replacements, keeping
    owner, SECURITY DEFINER, settings and privileges; it is forward-only."""
    with psycopg.connect(migrated_database_url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            acl = connection.execute(
                "SELECT array_length(proacl,1),prosecdef,proconfig::text "
                "FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                (function,),
            ).fetchone()
            assert acl == (1, True, "{search_path=pg_catalog}"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261122_118"
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

    with _temporary_migration_database("settlement_pet_payback") as temporary:
        alembic_command.upgrade(config, "20261122_118")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
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
