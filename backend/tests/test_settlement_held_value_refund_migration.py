"""Post-settlement correction: the refund-only form HELD_VALUE_REFUND (V1-056 sub-slice 10c-2b-3).

Owner answer 3 to Q-2026-10-07-42 and answers 1, 2 and 4 to Q-2026-10-08-55: a later correction
refunds value that an earlier return-only REFUND_RETURN correction left, linked to that
correction. A held Credit first pays its own Customer's open debt on the Lease, and only the rest,
at most what the earlier correction left, is refunded to that Customer (BR-CREDIT-006,
BR-CREDIT-008); held Deposit money first pays the Lease's open debt in the DL-032 order and the
plan's Deposit Refund step refunds the rest (BR-SETTLE-008, BR-REFUND-015). Staff prepare it under
final_settlements.prepare and only financial.approve confirms it (BR-SETTLE-013, BR-AUTH-010).
"""

from __future__ import annotations

from dataclasses import replace
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

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    PetRemainderDecision,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementStep,
)
from property_rental.refund import CreateUsdRefundCommand
from property_rental.settlement_correction import RecordHeldValueRefundCorrectionCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import (
    LINE,
    PET_REST,
    STAFF,
    leaving_case,
    two_signer_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, preparer
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_return_migration import effect_links, pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_pet_refund_return_migration import reviewed_case
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import (
    really_close,
    third_party_payment,
    unpaid_charge,
)
from test_settlement_refund_correction_migration import record as record_refund_correction
from test_settlement_refund_return_migration import (
    NOTE,
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
)

REASON = "The returned Refund is paid out again"
RECORD = "app.record_settlement_held_value_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_held_value_refund(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_held_credit_value(uuid,uuid,uuid)",
    "app.settlement_held_credit_left(uuid,uuid)",
    "app.settlement_held_deposit_value(uuid,uuid)",
    "app.settlement_held_value_input(jsonb)",
    "app.settlement_held_value_source_state(uuid,uuid)",
    "app.settlement_held_value_plan(uuid,uuid,jsonb)",
)
CHANGED = {
    "app.lock_settlement_correction_plan(uuid)": "LOCK_PLAN_REPLACEMENTS",
    "app.settlement_correction_refund_allowed(app.refunds)": "REFUND_ALLOWED_REPLACEMENTS",
}
NOTHING_LEFT = "Nothing the earlier correction returned is left to refund"
CREDIT_EMPTY = "The Credit holds no returned value to refund"
DEPOSIT_EMPTY = "The Deposit holds no returned money to refund"
EVERY_BALANCE = "Every remaining Deposit balance must be applied or refunded"
COUNTS = (
    "SELECT (SELECT count(*) FROM app.financial_drafts),"
    "(SELECT count(*) FROM app.settlement_corrections),(SELECT count(*) FROM app.refunds),"
    "(SELECT count(*) FROM app.deposit_applications),"
    "(SELECT count(*) FROM app.customer_credit_applications)"
)


def return_only(case: dict[str, Any], refund: object, amount: int, *steps: SettlementStep) -> UUID:
    """A confirmed return-only REFUND_RETURN correction; its id."""
    result = confirm(case, record(case, return_command(case, refund, amount, *steps, new=False)))
    return UUID(str(result["settlement_correction"]["id"]))


def held_command(
    case: dict[str, Any],
    earlier: object,
    *steps: SettlementStep,
    pet_remainder: PetRemainderDecision | None = None,
) -> RecordHeldValueRefundCorrectionCommand:
    return RecordHeldValueRefundCorrectionCommand(
        uuid4(),
        case["settlement"],
        UUID(str(earlier)),
        REASON,
        case["cash"],
        NOTE,
        tuple(steps),
        pet_remainder,
    )


def credit_left(url: str, earlier: object, credit: object) -> int:
    """What the earlier correction left in the Credit (owner answer 1 to Q-2026-10-09-63)."""
    return int(one(url, "SELECT app.settlement_held_credit_value(%s,%s,NULL)", earlier, credit)[0])


def deposit_left(url: str, earlier: object, deposit: object) -> int:
    """What the earlier correction left in the Deposit (owner answer 1 to Q-2026-10-09-63)."""
    return int(one(url, "SELECT app.settlement_held_deposit_value(%s,%s)", earlier, deposit)[0])


def audit(url: str, correction: object) -> tuple[Any, dict[str, Any]]:
    """The confirm's audit event: its customer and its resulting state."""
    return cast(
        tuple[Any, dict[str, Any]],
        one(
            url,
            "SELECT customer_id,resulting_state FROM app.audit_events WHERE correlation_id=%s "
            "AND action='final_settlement.correction.confirmed'",
            correction,
        ),
    )


def record_held(case: dict[str, Any], command: RecordHeldValueRefundCorrectionCommand) -> UUID:
    found = corrections().record_held_value_refund(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm_held(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_held_value_refund(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def test_a_held_credit_first_pays_its_customer_s_debt_and_only_the_rest_is_refunded(
    migrated_database_url: str,
) -> None:
    """Owner answers 1 and 2 to Q-2026-10-08-55: a correction's Credit Refund (2,000) comes back
    through two return-only corrections (1,800, then 200), so the Credit holds 2,000. The Customer
    then owes a 1,500 charge. A held-value Refund linked to the first, without a plan, is refused
    (the Credit pays its Customer's debt first); Staff cannot confirm one; with the plan the
    approver's confirm applies 1,500 of the Credit to the charge and refunds the rest (500) to the
    same Customer with the draft's method and note: what is left in the Credit after the step, at
    most what the first correction left (1,800), so this correction's own step application does
    not lower that cap (owner answer 2 to Q-2026-10-09-63, as built; the stricter rule would refund
    300). Nothing is left, so a second one is refused. The Settlement row is unchanged, the ledger
    reconciles and an exact repeat replays."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    earlier = return_only(case, refund, 1_800)
    return_only(case, refund, 200)
    assert available(url, credit) == 2_000
    _, charge_line = unpaid_charge(url, case, case["person"])
    before = settlement_row(url, case["settlement"])
    with pytest.raises(FinalSettlementConflictError) as unplanned:
        record_held(case, held_command(case, earlier))
    assert cause(unplanned) == (
        "55000",
        "Customer Credit the correction releases pays its own Customer's open debt on this Lease "
        "before any Refund",
    )
    draft = record_held(
        case, held_command(case, earlier, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    )
    assert one(
        url,
        "SELECT payload->>'variant',payload->>'held_from_settlement_correction_id',"
        "payload->>'customer_credit_id' FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == ("HELD_VALUE_REFUND", str(earlier), str(credit))
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_held_value_refund(
            case["prop"], draft, actor=preparer(case["human"], case["prop"])
        )
    assert (available(url, credit), outstanding(url, charge_line)) == (2_000, 1_500)
    result = confirm_held(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == ["customer_credit_application_id", "refund_id"]
    [applied] = result["credit_applications"]
    assert (applied["customer_credit_id"], applied["amount_usd_cents"]) == (str(credit), 1_500)
    [paid] = result["refunds"]
    assert (
        paid["source_customer_credit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
        paid["reference_note"],
    ) == (str(credit), str(customer), 500, str(case["cash"]), NOTE)
    assert result["refund_corrections"] == []
    assert (available(url, credit), outstanding(url, charge_line), net(url, refund)) == (0, 0, 0)
    confirmed = one(
        url,
        "SELECT resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction,
    )[0]
    assert (confirmed["variant"], confirmed["held_from_settlement_correction_id"]) == (
        "HELD_VALUE_REFUND",
        str(earlier),
    )
    assert confirm_held(case, draft) == result
    with pytest.raises(FinalSettlementConflictError) as second:
        record_held(case, held_command(case, earlier))
    assert cause(second) == ("55000", NOTHING_LEFT)
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_held_deposit_money_is_refunded_by_a_later_correction(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-07-42 and owner answer 1 to Q-2026-10-09-63: the Settlement's
    Pet Deposit Refund comes back in part (2,000) through a return-only correction E, so the Pet
    Deposit holds 2,000 again. A held-value Refund with no plan is refused (every DL-032 Deposit
    balance must be applied or refunded); with the plan's Deposit Refund step the Pet Deposit's
    2,000 is refunded to the Customer. E then has nothing left. A second return-only correction E2
    returns 1,000 more: naming E again is refused and changes no money and no record; a correction
    linked to E2 lets the Customer's Credit (300) and then the Pet Deposit's 1,000 pay a new 1,500
    charge (no Refund; the audit names the Deposit's owner and every Deposit balance it settled),
    and E2's value is then gone too."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, customer = case["pet"], case["customer"]
    earlier = return_only(case, pet_refund(case), 2_000)
    assert (held(url, pet), deposit_left(url, earlier, pet)) == (2_000, 2_000)
    with pytest.raises(FinalSettlementConflictError) as unplanned:
        record_held(case, held_command(case, earlier))
    assert cause(unplanned) == ("55000", EVERY_BALANCE)
    result = confirm_held(
        case, record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 2_000)))
    )
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == ["refund_id"]
    [paid] = result["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
    ) == (str(pet), str(customer), 2_000, str(case["cash"]))
    customer_id, confirmed = audit(url, correction)
    assert (customer_id, confirmed["customer_id"], confirmed["settled_deposits"]) == (
        customer,
        str(customer),
        [{"deposit_id": str(pet), "applied_usd_cents": 0, "refunded_usd_cents": 2_000}],
    )
    assert (held(url, pet), deposit_left(url, earlier, pet)) == (0, 0)
    with pytest.raises(FinalSettlementConflictError) as second:
        record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 2_000)))
    assert cause(second) == ("55000", NOTHING_LEFT)
    later = return_only(case, pet_refund(case), 1_000)
    assert held(url, pet) == 1_000
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as again:
        record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    assert cause(again) == ("55000", NOTHING_LEFT)
    assert (one(url, COUNTS), held(url, pet)) == (before, 1_000)
    _, charge_line = unpaid_charge(url, case, case["person"])
    draft = record_held(
        case,
        held_command(
            case,
            later,
            SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
            SettlementDepositStep(PET_REST, pet, LINE, charge_line, 1_000),
            pet_remainder=STAFF,
        ),
    )
    paid_debt = confirm_held(case, draft)
    correction = paid_debt["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "customer_credit_application_id",
        "deposit_application_id",
    ]
    assert paid_debt["refunds"] == []
    customer_id, confirmed = audit(url, correction)
    assert (customer_id, confirmed["settled_deposits"]) == (
        customer,
        [{"deposit_id": str(pet), "applied_usd_cents": 1_000, "refunded_usd_cents": 0}],
    )
    assert (held(url, pet), outstanding(url, charge_line), deposit_left(url, later, pet)) == (
        0,
        200,
        0,
    )
    with pytest.raises(FinalSettlementConflictError) as gone:
        record_held(case, held_command(case, later))
    assert cause(gone) == ("55000", NOTHING_LEFT)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_held_value_refund_refuses_a_correction_that_left_nothing_and_a_stale_draft_waits(
    migrated_database_url: str,
) -> None:
    """Only a confirmed return-only correction of this Settlement leaves value: a returned-Refund
    correction that paid a new Refund is refused (55000), an unknown correction and a return-only
    correction of another closed Settlement are not found (P0002). The database guards: malformed
    input 22023; the recorder takes only final_settlements.prepare and the confirm only
    financial.approve (42501); a reused key P5205 and an exact repeat replays; a service identity
    that is not a person cannot confirm (P4506); the confirm runs only at READ COMMITTED (55000);
    nothing of a refused call is written. Two drafts on the same return-only correction: the first
    refunds the held 1,000 and holds the Lease row and the Credit row until it commits (NOWAIT);
    the second is stale (its sources changed) and stays pending, and it first waits for the Credit
    row another session holds, which shows that the confirm locks the Credit before its stale
    check (the lock function's patch)."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    paid_again = confirm(case, record(case, return_command(case, refund, 500)))
    with pytest.raises(FinalSettlementConflictError) as not_held:
        record_held(case, held_command(case, paid_again["settlement_correction"]["id"]))
    assert cause(not_held) == (
        "55000",
        "Only a return-only returned-Refund correction leaves value for a later Refund",
    )
    with pytest.raises(FinalSettlementNotFoundError):
        record_held(case, held_command(case, uuid4()))
    earlier = return_only(case, refund, 1_000)
    other_settlement = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    other_settlement["person"] = approver(url)
    really_close(other_settlement)
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        record_held(
            case, replace(held_command(case, earlier), settlement_id=other_settlement["settlement"])
        )
    assert cause(elsewhere) == ("P0002", "Post-settlement correction was not found")
    before = one(url, COUNTS)
    good = held_command(case, earlier).held_value()
    for malformed in (
        {**good, "surprise": True},
        {key: value for key, value in good.items() if key != "new_refund"},
        {**good, "held_from_settlement_correction_id": "not-a-uuid"},
        {**good, "new_refund": {"refund_method_id": str(case["cash"]), "reference_note": " pad"}},
        {**good, "new_refund": {"refund_method_id": str(case["cash"])}},
        {**good, "plan": []},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (
                    case["prop"],
                    case["human"],
                    uuid4(),
                    case["settlement"],
                    Jsonb(malformed),
                    REASON,
                ),
            )
        assert refused.value.sqlstate == "22023", malformed
    for authorization in ("financial.approve", "refunds.create", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (
                    case["prop"],
                    case["human"],
                    uuid4(),
                    case["settlement"],
                    Jsonb(good),
                    REASON,
                    authorization,
                ),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert one(url, COUNTS) == before
    reused = held_command(case, earlier)
    first = record_held(case, reused)
    assert record_held(case, reused) == first
    with pytest.raises(FinalSettlementKeyReused):
        record_held(case, replace(reused, reason="Another reason for the same key"))
    other = record_held(case, held_command(case, earlier))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (case["prop"], case["person"], first),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(
            connection, property_id=case["prop"], created_by=case["human"]
        )
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_held_value_refund(
            case["prop"], first, actor=approving(machine, case["prop"])
        )
    assert cause(not_a_person)[0] == "P4506"
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert (state(url, first), available(url, credit)) == ("PENDING", 1_000)
    lease = one(url, "SELECT lease_id FROM app.final_settlements WHERE id=%s", case["settlement"])[
        0
    ]
    with psycopg.connect(url) as holder:
        found = holder.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], first),
        ).fetchone()
        assert found is not None
        [paid] = cast(dict[str, Any], found[0])["refunds"]
        assert paid["amount_usd_cents"] == 1_000
        for query, value in (
            ("SELECT 1 FROM app.leases WHERE id=%s FOR UPDATE NOWAIT", lease),
            ("SELECT 1 FROM app.customer_credits WHERE id=%s FOR UPDATE NOWAIT", credit),
        ):
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
            ):
                waiting.execute(query, (value,))
    assert state(url, first) == "CONFIRMED"
    # The lock function's patch (review round 2): the confirm takes the Credit in its id-ordered
    # pass before its stale check, so while another session holds the Credit row the stale draft
    # waits for that lock (lock_timeout, 55P03) instead of being reported stale at once; the
    # Refund insert, which locks the Credit too, is never reached by a stale draft.
    with psycopg.connect(url) as holding:
        holding.execute("SELECT 1 FROM app.customer_credits WHERE id=%s FOR UPDATE", (credit,))
        with (
            pytest.raises(psycopg.errors.LockNotAvailable),
            psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
        ):
            waiting.execute("SET lock_timeout='1s'")
            waiting.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                (case["prop"], case["person"], other),
            )
        holding.rollback()
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm_held(case, other)
    assert state(url, other) == "PENDING"
    assert available(url, credit) == 0


def test_a_held_third_party_credit_is_refunded_to_its_customer_within_what_was_left(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014: a correction's Credit Refund to the Invoice Customer of value released from a
    third-party Payment comes back in two return-only corrections (200, then 100), so the Credit
    holds more (300) than the first one left. A held-value Refund linked to the first pays those
    200 to the same Customer, not the payer, through the relaxed Credit Refund check, which counts
    what the earlier correction left and nothing more: a second linked Refund of 1 cent from the
    same Credit, processed by the approver with its details row, is refused although the Credit
    still holds value; everything of that attempt rolls back and the draft stays pending. After the
    confirm the first correction has nothing left and is refused; the second one's 100 are
    refunded."""
    url = migrated_database_url
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    customer = case["customer"]
    case["person"] = approver(url)
    really_close(case)
    invoice, line = unpaid_charge(url, case, case["person"])
    payer, _ = third_party_payment(url, case, invoice, line, 1_500)
    result = cast(
        dict[str, Any],
        corrections().confirm_refund(
            case["prop"],
            record_refund_correction(case, refund_correction(case, invoice, line, 500)),
            actor=approving(case["person"], case["prop"]),
        ),
    )
    [paid] = result["refunds"]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    earlier = return_only(case, refund, 200)
    later = return_only(case, refund, 100)
    assert (available(url, credit), credit_left(url, earlier, credit)) == (300, 200)
    draft = record_held(case, held_command(case, earlier))
    second = uuid4()
    with pytest.raises(psycopg.Error) as capped, psycopg.connect(url) as connection:
        found = connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert found is not None
        inside = cast(dict[str, Any], found[0])
        [first] = inside["refunds"]
        assert (first["recipient_customer_id"], first["amount_usd_cents"]) == (str(customer), 200)
        correction = inside["settlement_correction"]["id"]
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(
            "SELECT app.link_settlement_correction_effect(%s,'refund_id',%s)", (correction, second)
        )
        connection.execute(
            "INSERT INTO app.settlement_correction_refund_details(refund_id,"
            "settlement_correction_id,draft_id,refund_method_id,reference_note,recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,clock_timestamp())",
            (second, correction, draft, case["cash"], NOTE),
        )
        assert connection.execute(
            "SELECT app.credit_available_value(%s)", (credit,)
        ).fetchone() == (100,)
        connection.execute(
            "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,"
            "source_customer_credit_id,usd_accounting_value_cents,refund_currency,"
            "refund_amount_minor,reason,processed_at,processed_by,authorization_reference) "
            "VALUES (%s,%s,%s,%s,1,'USD',1,'Direct',GREATEST(clock_timestamp(),"
            "app.credit_latest_at(%s)+interval '1 microsecond'),%s,'refunds.create')",
            (second, f"REF-{second}", customer, credit, credit, case["person"]),
        )
    assert (capped.value.sqlstate, capped.value.diag.message_primary) == (
        "23514",
        "Refund source, amount, authorization or chronology is invalid",
    )
    assert (state(url, draft), available(url, credit)) == ("PENDING", 300)
    [again] = confirm_held(case, draft)["refunds"]
    assert (again["recipient_customer_id"], again["amount_usd_cents"]) == (str(customer), 200)
    assert (available(url, credit), credit_left(url, earlier, credit)) == (100, 0)
    with pytest.raises(FinalSettlementConflictError) as gone:
        record_held(case, held_command(case, earlier))
    assert cause(gone) == ("55000", NOTHING_LEFT)
    [rest] = confirm_held(case, record_held(case, held_command(case, later)))["refunds"]
    assert (rest["recipient_customer_id"], rest["amount_usd_cents"]) == (str(customer), 100)
    assert available(url, credit) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
        events = {str(event["event_id"]) for event in history(connection, customer)}
        assert {again["id"], rest["id"]} <= events
        assert not {again["id"], rest["id"]} & {
            str(event["event_id"]) for event in history(connection, payer)
        }


def test_what_an_earlier_correction_left_caps_the_refund_after_its_own_step_paid_debt(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-08-55 and owner answer 1 to Q-2026-10-09-63: the Customer owes
    a 1,500 charge when a return-only correction E brings back 1,800 of a correction's Credit
    Refund; E's own step applies 1,500 of the Credit to the charge, so E leaves 300. A second
    return-only correction E2 brings back the last 200, so the Credit holds 500, more than E left.
    A held-value Refund linked to E refunds only E's 300; E is then refused (nothing left) and a
    held-value Refund linked to E2 refunds its 200."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    _, charge_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(
        case, refund, 1_800, SettlementCreditStep(credit, LINE, charge_line, 1_500)
    )
    assert (outstanding(url, charge_line), available(url, credit)) == (0, 300)
    assert credit_left(url, earlier, credit) == 300
    later = return_only(case, refund, 200)
    assert (available(url, credit), net(url, refund)) == (500, 0)
    [paid] = confirm_held(case, record_held(case, held_command(case, earlier)))["refunds"]
    assert (paid["recipient_customer_id"], paid["amount_usd_cents"]) == (str(customer), 300)
    assert (available(url, credit), credit_left(url, earlier, credit)) == (200, 0)
    with pytest.raises(FinalSettlementConflictError) as gone:
        record_held(case, held_command(case, earlier))
    assert cause(gone) == ("55000", NOTHING_LEFT)
    [rest] = confirm_held(case, record_held(case, held_command(case, later)))["refunds"]
    assert (rest["recipient_customer_id"], rest["amount_usd_cents"]) == (str(customer), 200)
    assert available(url, credit) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_credit_return_while_a_deposit_holds_money_is_refunded_with_that_money(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-08-59, owner answers 1 and 2 to Q-2026-10-09-63 and the owner
    answer to Q-2026-10-09-64 (sub-slice 10c-2b-4): the Pet Deposit holds 2,000 that a return-only
    correction Ed brought back; a return-only correction Ec of a correction's Credit Refund (1,000)
    is still recorded. The Customer then spends 600 of that Credit through an ordinary Credit
    Refund, which lowers only the Credit's available value (the known limit: Ec still shows 1,000
    left). A held-value Refund linked to Ec may use no Deposit money, because Ec returned none:
    with the Pet Deposit's Refund step it is refused and writes nothing; without it, it refunds
    the Credit's 400 (capped by what it holds) and the Pet Deposit keeps its 2,000. A correction
    linked to Ed refunds those 2,000 and its audit lists that Deposit balance; Ed then has nothing
    left and naming it again is refused. When the Pet Deposit holds 500 again, a correction linked
    to Ec is refused because the Credit holds nothing, although its plan has a Deposit Refund
    step; no record is written; a correction linked to the new return refunds the 500."""
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
    assert (held(url, pet), available(url, credit)) == (2_000, 1_000)
    create_usd_refund(
        refunds(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 600, "Customer asked for part"),
        actor=refund_actor(case["human"], case["prop"], "refunds.create"),
    )
    assert (available(url, credit), credit_left(url, credit_return, credit)) == (400, 1_000)
    counted = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as beyond:
        record_held(case, held_command(case, credit_return, settlement_refund(case, "pet", 2_000)))
    assert cause(beyond) == (
        "55000",
        "A held-value correction uses at most what its earlier correction left in each Deposit",
    )
    assert (one(url, COUNTS), held(url, pet), available(url, credit)) == (counted, 2_000, 400)
    result = confirm_held(case, record_held(case, held_command(case, credit_return)))
    assert {
        (paid["source_customer_credit_id"], paid["source_deposit_id"], paid["amount_usd_cents"])
        for paid in result["refunds"]
    } == {(str(credit), None, 400)}
    customer_id, confirmed = audit(url, result["settlement_correction"]["id"])
    assert (customer_id, confirmed["settled_deposits"]) == (customer, [])
    assert (held(url, pet), available(url, credit)) == (2_000, 0)
    assert (credit_left(url, credit_return, credit), deposit_left(url, deposit_return, pet)) == (
        600,
        2_000,
    )
    result = confirm_held(
        case,
        record_held(
            case, held_command(case, deposit_return, settlement_refund(case, "pet", 2_000))
        ),
    )
    assert {
        (paid["source_customer_credit_id"], paid["source_deposit_id"], paid["amount_usd_cents"])
        for paid in result["refunds"]
    } == {(None, str(pet), 2_000)}
    customer_id, confirmed = audit(url, result["settlement_correction"]["id"])
    assert (customer_id, confirmed["settled_deposits"]) == (
        customer,
        [{"deposit_id": str(pet), "applied_usd_cents": 0, "refunded_usd_cents": 2_000}],
    )
    assert (held(url, pet), deposit_left(url, deposit_return, pet)) == (0, 0)
    with pytest.raises(FinalSettlementConflictError) as emptied:
        record_held(case, held_command(case, deposit_return, settlement_refund(case, "pet", 2_000)))
    assert cause(emptied) == ("55000", NOTHING_LEFT)
    newest = return_only(case, pet_refund(case), 500)
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as no_credit:
        record_held(case, held_command(case, credit_return, settlement_refund(case, "pet", 500)))
    assert cause(no_credit) == ("55000", CREDIT_EMPTY)
    assert (one(url, COUNTS), held(url, pet)) == (before, 500)
    [paid] = confirm_held(
        case, record_held(case, held_command(case, newest, settlement_refund(case, "pet", 500)))
    )["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 500)
    assert held(url, pet) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_deposit_correction_audit_names_the_refund_recipient(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent N9, security N6): the Settlement refunded the Pet Deposit's
    rest to the other signed Signer with the written agreement of all Signers (BR-REFUND-015);
    part of it comes back through a return-only correction. A held-value Refund that pays it to
    the Primary Tenant records the Primary Tenant (the Deposit's owner and the new Refund's
    recipient) on its draft and on its audit event, not the earlier Refund's recipient. A second
    return comes back and is paid to the Signer with the agreement: the draft names the Deposit's
    owner and the audit event names the Signer, the new Refund's recipient (review round 2)."""
    url = migrated_database_url
    case = {**two_signer_case(url), "url": url}
    agreement = "All Signers agreed in writing on 2026-10-09 that the Signer receives the Refund"
    pet, tenant, co_signer = case["pet"], case["tenant"], case["co_signer"]
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, pet, LINE, case["tenant_line"], 1_500),
                SettlementDepositStep(PET_REST, pet, LINE, case["signer_line"], 600),
                settlement_refund(
                    case, "pet", 17_900, recipient_customer_id=co_signer, signer_agreement=agreement
                ),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    earlier = return_only(case, pet_refund(case), 1_000)
    assert one(
        url, "SELECT recipient_customer_id FROM app.refunds WHERE id=%s", pet_refund(case)
    ) == (co_signer,)
    draft = record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    assert one(
        url, "SELECT payload->>'customer_id' FROM app.financial_drafts WHERE id=%s", draft
    ) == (str(tenant),)
    result = confirm_held(case, draft)
    [paid] = result["refunds"]
    assert (paid["recipient_customer_id"], paid["amount_usd_cents"]) == (str(tenant), 1_000)
    customer_id, confirmed = audit(url, result["settlement_correction"]["id"])
    assert (customer_id, confirmed["customer_id"]) == (tenant, str(tenant))
    assert held(url, pet) == 0
    later = return_only(case, pet_refund(case), 500)
    to_signer = settlement_refund(
        case, "pet", 500, recipient_customer_id=co_signer, signer_agreement=agreement
    )
    draft = record_held(case, held_command(case, later, to_signer))
    assert one(
        url, "SELECT payload->>'customer_id' FROM app.financial_drafts WHERE id=%s", draft
    ) == (str(tenant),)
    result = confirm_held(case, draft)
    [paid] = result["refunds"]
    assert (paid["recipient_customer_id"], paid["signer_agreement"]) == (str(co_signer), agreement)
    customer_id, confirmed = audit(url, result["settlement_correction"]["id"])
    assert (customer_id, confirmed["customer_id"]) == (co_signer, str(co_signer))
    assert held(url, pet) == 0


def test_held_pet_deposit_money_off_the_dl032_path_waits_for_the_owner(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-09-61 is open: after a pet noncompliance termination (BR-DEP-022) the kept Pet
    Deposit holds a returned Pet Refund-review Refund (2,000); a held-value Refund of it is refused
    (55000, only on the DL-032 path) and no draft is recorded."""
    url = migrated_database_url
    case = reviewed_case(url, pet_noncompliance=True)
    earlier = return_only(case, case["review_refund"], 2_000)
    assert held(url, case["pet"]) == 2_000
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 2_000)))
    assert cause(refused) == (
        "55000",
        "A returned Deposit pays debt or is refunded again only on the DL-032 path",
    )
    assert one(
        url,
        "SELECT count(*) FROM app.financial_drafts WHERE payload->>'variant'='HELD_VALUE_REFUND' "
        "AND payload->>'final_settlement_id'=%s",
        str(case["settlement"]),
    ) == (0,)
    assert held(url, case["pet"]) == 2_000


def test_held_value_refund_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms a held-value Refund correction; no role calls
    its internal functions; the migration adds only its functions, changes only the two patched
    functions (each new body exactly the old one with its replacements, privileges, owner, SECURITY
    DEFINER and settings kept) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261114_110")
    assert revision is not None and revision.down_revision == "20261113_109"
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

    with _temporary_migration_database("settlement_held_value_refund") as temporary:
        alembic_command.upgrade(config, "20261113_109")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261114_110")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
