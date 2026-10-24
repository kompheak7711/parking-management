"""Post-settlement correction: a returned Credit Refund of a correction (V1-056 sub-slice 10c-2b-1).

Owner answer 4 to the sub-slice 10c-1b review record (approved tightening): a Refund that a
post-settlement correction paid is corrected only through another post-settlement correction, never
by the one-call verified return or its one-call reversal. Owner answers 1, 2 and 4 to
Q-2026-10-08-55: the REFUND_RETURN correction records the verified return, so the value goes back to
the Credit; that Credit first pays its own Customer's open debt on the Lease through the shared
DL-032 step (BR-CREDIT-006, BR-CREDIT-008), whether or not a new Refund is paid; only the rest is
refunded to the same Customer (BR-CREDIT-014, BR-REFUND-014) or stays as that Customer's Credit.
Staff prepare it under final_settlements.prepare and only financial.approve confirms it
(BR-SETTLE-013, BR-AUTH-010).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
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

from payment_test_support import database_instant
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
)
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundInvalidError,
    ReverseRefundCorrectionCommand,
)
from property_rental.settlement_correction import RecordRefundReturnCorrectionCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, leaving_case
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one, outstanding, preparer
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import (
    really_close,
    third_party_payment,
    unpaid_charge,
)
from test_settlement_refund_correction_migration import record as record_refund_correction
from test_unpaid_initial_termination_migration import rent_line

RECORD = "app.record_settlement_refund_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_refund_return(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_refund_return_settlement(uuid)",
    "app.settlement_refund_return_allowed(app.refund_corrections)",
    "app.settlement_refund_return_input(jsonb)",
    "app.settlement_refund_return_source_state(uuid,uuid)",
    "app.settlement_refund_return_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_return_overlay(jsonb)",
    "app.settlement_refund_return_result(uuid)",
)
CHANGED = {
    "app.require_correctable_usd_refund(uuid,uuid)": "CORRECTABLE_REPLACEMENTS",
    "app.validate_general_refund_correction()": "GENERAL_CORRECTION_REPLACEMENTS",
    "app.settlement_correction_refund_allowed(app.refunds)": "REFUND_ALLOWED_REPLACEMENTS",
    "app.lock_settlement_correction_plan(uuid)": "LOCK_PLAN_REPLACEMENTS",
}
REASON = "The bank returned the Refund transfer"
METHOD_REFERENCE = "Bank return BT-77"
EVIDENCE = "Bank statement line 4"
NOTE = "Cash handed over at the front desk"
ONLY_THROUGH = (
    "A post-settlement correction Refund is corrected only through a post-settlement correction"
)
NOT_RETURNABLE = "The returned Refund is not a Refund this correction may return"
COORDINATED = "Refund requires its source-specific coordinated correction path"
BEGIN = "SELECT app.begin_settlement_correction(%s,%s,%s,'financial.approve')"
RETURN_ROW = (
    "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
    "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
    "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,"
    "occurred_at,actor_id,authorization_reference,verified_return_amount_minor,"
    "verified_return_currency,verified_returned_at,return_method_reference) "
    "SELECT %s,refund.id,'VALUE_CORRECTION',%s,%s,app.refund_net_value_at(refund.id,'infinity'),"
    "app.refund_net_value_at(refund.id,'infinity')-%s,%s,%s,"
    "GREATEST(clock_timestamp(),app.credit_latest_at(refund.source_customer_credit_id)"
    "+interval '1 microsecond'),%s,%s,%s,'USD',%s,%s "
    "FROM app.refunds refund WHERE refund.id=%s"
)


def return_values(
    row: UUID,
    amount: int,
    actor_id: UUID,
    reference: str,
    at: object,
    refund: UUID,
    evidence: str = EVIDENCE,
    method: str = METHOD_REFERENCE,
    reason: str = REASON,
) -> tuple[object, ...]:
    """The parameters of RETURN_ROW: by default the draft's reason, evidence and method references
    (sub-slice 10c-2b-2a binds the reason too, so the rows carry the draft's reason; owner answer 3
    to Q-2026-10-08-59)."""
    return (
        row,
        amount,
        amount,
        amount,
        reason,
        evidence,
        actor_id,
        reference,
        amount,
        at,
        method,
        refund,
    )


REVERSAL_ROW = (
    "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,"
    "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
    "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,"
    "occurred_at,actor_id,authorization_reference) "
    "SELECT %s,refund.id,'CORRECTION_REVERSAL',original.id,"
    "-original.source_balance_effect_usd_cents,-original.source_balance_effect_usd_cents,"
    "app.refund_net_value_at(refund.id,'infinity'),"
    "app.refund_net_value_at(refund.id,'infinity')+original.source_balance_effect_usd_cents,"
    "'Direct','Direct evidence',GREATEST(clock_timestamp(),"
    "app.credit_latest_at(refund.source_customer_credit_id)+interval '1 microsecond'),%s,%s "
    "FROM app.refund_corrections original JOIN app.refunds refund ON refund.id=original.refund_id "
    "WHERE original.id=%s AND refund.id=%s"
)


def now(url: str) -> Any:
    with psycopg.connect(url) as connection:
        return database_instant(connection)


def return_command(
    case: dict[str, Any], refund: object, amount: int, *steps: Any, **changes: Any
) -> RecordRefundReturnCorrectionCommand:
    """A returned Refund with a new Refund by default; ``new=False`` records the return only."""
    new = changes.pop("new", True)
    return replace(
        RecordRefundReturnCorrectionCommand(
            uuid4(),
            case["settlement"],
            UUID(str(refund)),
            amount,
            now(case["url"]),
            METHOD_REFERENCE,
            EVIDENCE,
            REASON,
            case["cash"] if new else None,
            NOTE if new else None,
            tuple(steps),
        ),
        **changes,
    )


def record(case: dict[str, Any], command: RecordRefundReturnCorrectionCommand) -> UUID:
    found = corrections().record_refund_return(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_refund_return(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def net(url: str, refund: object) -> int:
    return int(one(url, "SELECT app.refund_net_value_at(%s,'infinity')", refund)[0])


def available(url: str, credit: object) -> int:
    return int(one(url, "SELECT app.credit_available_value(%s)", credit)[0])


def effect_links(url: str, correction: object) -> list[str]:
    names = ("refund_correction_id", "refund_id", "customer_credit_application_id")
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(names)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    return [next(name for name, value in zip(names, row, strict=True) if value) for row in rows]


def refunded_case(url: str, amount: int = 2_000) -> dict[str, Any]:
    """The closed 8c Settlement (sub-slice 10c-2a-2) and a REFUND correction of the Initial
    Invoice's Rent line that pays the released Payment value back to the Customer, who paid it
    and owes nothing on the Lease: one Credit Refund a correction paid."""
    case = {**closed_case(url), "url": url}
    rent, _ = rent_line(url, case["initial"])
    result = confirm_refund(case, record_refund(case, refund_command(case, rent, amount)))
    [paid] = result["refunds"]
    assert (paid["amount_usd_cents"], paid["recipient_customer_id"]) == (
        amount,
        str(case["customer"]),
    )
    case["refund"] = UUID(str(paid["id"]))
    case["refund_credit"] = UUID(str(paid["source_customer_credit_id"]))
    assert available(url, case["refund_credit"]) == 0
    return case


def test_a_returned_correction_refund_is_corrected_only_through_a_correction(
    migrated_database_url: str,
) -> None:
    """Owner answer 4 to the 10c-1b review record and answers 1 and 4 to Q-2026-10-08-55: the
    one-call verified return of a correction's Credit Refund is refused, and a direct Refund
    correction row too; Staff record a REFUND_RETURN draft with no effect and cannot confirm it;
    a financial.approve holder confirms it, which writes the verified return (financial.approve,
    linked first) and, the Customer owing nothing on the Lease, one new Refund of the returned
    amount to the same Customer with the draft's method and note. The new Refund and the return
    are not corrected with one call either; the Settlement row is unchanged; the ledger
    reconciles; an exact repeat replays."""
    url = migrated_database_url
    case = refunded_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    refund, credit = case["refund"], case["refund_credit"]
    with pytest.raises(RefundInvalidError) as one_call:
        refunds().verify_usd_return(
            prop, refund, returned(500), actor=refund_actor(human, prop, "refunds.correct")
        )
    assert cause(one_call) == ("P5202", COORDINATED)
    with pytest.raises(psycopg.Error) as direct, psycopg.connect(url) as connection:
        connection.execute(
            RETURN_ROW, return_values(uuid4(), 500, human, "refunds.correct", now(url), refund)
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == ("23514", ONLY_THROUGH)
    before = settlement_row(url, case["settlement"])
    draft = record(case, return_command(case, refund, 2_000))
    assert state(url, draft) == "PENDING"
    assert (net(url, refund), available(url, credit)) == (2_000, 0)
    stored = one(
        url,
        "SELECT payload->'refund_return',payload->'plan_overlay',payload->>'customer_credit_id' "
        "FROM app.financial_drafts WHERE id=%s",
        draft,
    )
    assert stored[0]["new_refund"] == {
        "refund_method_id": str(case["cash"]),
        "reference_note": NOTE,
    }
    assert stored[1]["credits"] == {
        str(credit): {
            "customer_id": str(customer),
            "add_usd_cents": 2_000,
            "released_payment_allocation_id": None,
        }
    }
    assert stored[2] == str(credit)
    # Staff cannot confirm: the service refuses before any connection, and the database refuses
    # any other authorization reference and a billing service identity; the recorder takes only
    # final_settlements.prepare (review round 1).
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_refund_return(prop, draft, actor=preparer(human, prop))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,%s)",
            (prop, human, draft, "final_settlements.prepare"),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        service_actor = register_billing_service_principal(
            connection, property_id=prop, created_by=human
        )
    with pytest.raises(psycopg.Error) as service, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, service_actor, draft),
        )
    assert (service.value.sqlstate, service.value.diag.message_primary) == (
        "P4506",
        "Invoice command requires an active human actor",
    )
    for authorization in ("financial.approve", "refunds.correct", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    uuid4(),
                    case["settlement"],
                    Jsonb(return_command(case, refund, 2_000).refund_return()),
                    REASON,
                    authorization,
                ),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert state(url, draft) == "PENDING"
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == ["refund_correction_id", "refund_id"]
    [returned_row] = result["refund_corrections"]
    assert (
        returned_row["refund_id"],
        returned_row["correction_kind"],
        returned_row["returned_amount_usd_cents"],
        returned_row["previous_net_refund_usd_cents"],
        returned_row["resulting_net_refund_usd_cents"],
        returned_row["return_method_reference"],
        returned_row["evidence_reference"],
        returned_row["actor_id"],
        returned_row["authorization_reference"],
    ) == (
        str(refund),
        "VALUE_CORRECTION",
        2_000,
        2_000,
        0,
        METHOD_REFERENCE,
        EVIDENCE,
        str(case["person"]),
        "financial.approve",
    )
    [paid] = result["refunds"]
    assert (
        paid["recipient_customer_id"],
        paid["source_customer_credit_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
        paid["reference_note"],
        paid["processed_by"],
        paid["authorization_reference"],
    ) == (
        str(customer),
        str(credit),
        2_000,
        str(case["cash"]),
        NOTE,
        str(case["person"]),
        "refunds.create",
    )
    assert result["credit_applications"] == []
    assert (net(url, refund), available(url, credit)) == (0, 0)
    assert settlement_row(url, case["settlement"]) == before
    confirmed = one(
        url,
        "SELECT resulting_state,authorization_reference FROM app.audit_events "
        "WHERE correlation_id=%s AND action='final_settlement.correction.confirmed'",
        correction,
    )
    assert confirmed[1] == "financial.approve"
    assert (
        confirmed[0]["variant"],
        confirmed[0]["refund_id"],
        confirmed[0]["refund_correction_id"],
        confirmed[0]["returned_amount_usd_cents"],
        [item["refund_id"] for item in confirmed[0]["refunds"]],
    ) == ("REFUND_RETURN", str(refund), returned_row["id"], 2_000, [paid["id"]])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
    assert confirm(case, draft) == result
    # Neither the return nor the new Refund is corrected with one call (owner answer 4 to the
    # 10c-1b review record; owner answer 4 to Q-2026-10-07-41).
    with pytest.raises(RefundInvalidError) as reversal:
        refunds().reverse_correction(
            prop,
            refund,
            UUID(str(returned_row["id"])),
            ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Wrong return"),
            actor=refund_actor(human, prop, "refunds.corrections.reverse"),
        )
    assert cause(reversal) == ("P5202", COORDINATED)
    with pytest.raises(RefundInvalidError) as new_refund_return:
        refunds().verify_usd_return(
            prop,
            UUID(str(paid["id"])),
            returned(100),
            actor=refund_actor(human, prop, "refunds.correct"),
        )
    assert cause(new_refund_return) == ("P5202", COORDINATED)
    assert net(url, refund) == 0


def test_the_returned_credit_first_pays_its_customer_s_open_debt_on_the_lease(
    migrated_database_url: str,
) -> None:
    """Owner answers 1 and 2 to Q-2026-10-08-55 (BR-CREDIT-006, BR-CREDIT-008): once the Customer
    owes a 1,500 charge issued after closure, a return of 800 without a plan is refused, with or
    without a new Refund; with the plan the returned Credit pays 800 of the charge and the new
    Refund asked for is not paid, as nothing is left (review round 2); a return-only correction of
    400 pays 400 more; a last return of 800 with a new Refund pays the 300 still owed first and
    refunds only the rest (500)."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    for new in (False, True):
        with pytest.raises(FinalSettlementConflictError) as unplanned:
            record(case, return_command(case, refund, 800, new=new))
        assert cause(unplanned) == (
            "55000",
            "Customer Credit the correction releases pays its own Customer's open debt on this "
            "Lease before any Refund",
        ), new
    first = confirm(
        case,
        record(
            case,
            return_command(case, refund, 800, SettlementCreditStep(credit, LINE, charge_line, 800)),
        ),
    )
    [applied] = first["credit_applications"]
    assert (applied["customer_credit_id"], applied["invoice_id"], applied["amount_usd_cents"]) == (
        str(credit),
        str(charge_invoice),
        800,
    )
    assert first["refunds"] == []
    assert effect_links(url, first["settlement_correction"]["id"]) == [
        "refund_correction_id",
        "customer_credit_application_id",
    ]
    assert (net(url, refund), available(url, credit), outstanding(url, charge_line)) == (
        1_200,
        0,
        700,
    )
    kept = confirm(
        case,
        record(
            case,
            return_command(
                case, refund, 400, SettlementCreditStep(credit, LINE, charge_line, 400), new=False
            ),
        ),
    )
    assert kept["refunds"] == []
    assert (net(url, refund), available(url, credit), outstanding(url, charge_line)) == (
        800,
        0,
        300,
    )
    second = confirm(
        case,
        record(
            case,
            return_command(case, refund, 800, SettlementCreditStep(credit, LINE, charge_line, 300)),
        ),
    )
    assert effect_links(url, second["settlement_correction"]["id"]) == [
        "refund_correction_id",
        "customer_credit_application_id",
        "refund_id",
    ]
    [rest] = second["refunds"]
    assert (rest["source_customer_credit_id"], rest["amount_usd_cents"]) == (str(credit), 500)
    # The original Refund is fully returned; the 500 left after the charge is the new Refund.
    assert (net(url, refund), available(url, credit), outstanding(url, charge_line)) == (0, 0, 0)
    assert net(url, rest["id"]) == 500
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_third_party_credit_refund_is_paid_again_only_within_what_the_correction_returned(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014 and owner answer 2 to Q-2026-10-08-55: a correction's Credit Refund to the
    Invoice Customer of value released from a third-party Payment comes back in part; a
    return-only correction leaves 200 as that Customer's Credit, who owes nothing; a later
    correction returns 100 more and pays it again to the same Customer, not the payer, through the
    relaxed Credit Refund check, which accepts nothing beyond what the correction returned: a
    second linked Refund of 1 cent from the same Credit, processed by the approver with its
    details row, is refused although the Credit still holds value. Everything of that attempt
    rolls back and the draft stays pending; the confirm then succeeds."""
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
    assert one(url, "SELECT recipient_customer_id FROM app.refunds WHERE id=%s", refund) == (
        customer,
    )
    kept = confirm(case, record(case, return_command(case, refund, 200, new=False)))
    assert kept["refunds"] == [] and kept["credit_applications"] == []
    assert (net(url, refund), available(url, credit)) == (300, 200)
    draft = record(case, return_command(case, refund, 100))
    second = uuid4()
    with pytest.raises(psycopg.Error) as capped, psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.confirm_settlement_refund_return(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert found is not None
        inside = cast(dict[str, Any], found[0])
        [again] = inside["refunds"]
        assert (again["recipient_customer_id"], again["amount_usd_cents"]) == (str(customer), 100)
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
        ).fetchone() == (200,)
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
    assert state(url, draft) == "PENDING"
    assert (net(url, refund), available(url, credit)) == (300, 200)
    final = confirm(case, draft)
    [again] = final["refunds"]
    assert (again["recipient_customer_id"], again["amount_usd_cents"]) == (str(customer), 100)
    assert (net(url, refund), available(url, credit)) == (200, 200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
        assert again["id"] in {str(event["event_id"]) for event in history(connection, customer)}
        assert again["id"] not in {str(event["event_id"]) for event in history(connection, payer)}


def test_a_returned_refund_correction_refuses_wrong_input_and_a_stale_draft_waits(
    migrated_database_url: str,
) -> None:
    """Refusals: a Refund neither the Settlement nor a correction paid (an ordinary Credit Refund;
    sub-slice 10c-2b-2a made the Settlement's own Deposit Refund returnable) and an unknown
    Refund; more than the Refund's net value; a return dated before the Refund or in the future;
    a Deposit Refund step without a new Refund; malformed input and an impossible return date; a
    key reused for another correction. Two drafts return the same Refund: the second is stale
    after the first and stays pending. The confirm runs at READ COMMITTED and holds the Lease row
    and the returned Refund's Credit until it commits (the Refund correction and Refund checks
    lock that Credit too; the forward-only test pins the lock function's patch, review round 2)."""
    url = migrated_database_url
    case = refunded_case(url)
    refund = case["refund"]
    # Sub-slice 10c-2b-2a made the Settlement's own Deposit Refund returnable, so an ordinary
    # Credit Refund (the Customer's own 300 of Credit, refunded through its draft) stands in.
    ordinary = refund_id(
        create_usd_refund(
            refunds(),
            case["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", case["new_credit"], 300, "Return excess"),
            actor=refund_actor(case["human"], case["prop"], "refunds.create"),
        )
    )
    with pytest.raises(FinalSettlementConflictError) as deposit_refund:
        record(case, return_command(case, ordinary, 100))
    assert cause(deposit_refund) == ("55000", NOT_RETURNABLE)
    with pytest.raises(FinalSettlementNotFoundError):
        record(case, return_command(case, uuid4(), 100))
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, return_command(case, refund, 2_001))
    assert cause(too_much) == ("55000", "The returned amount exceeds the Refund's net value")
    processed = one(url, "SELECT processed_at FROM app.refunds WHERE id=%s", refund)[0]
    for when in (processed - timedelta(microseconds=1), now(url) + timedelta(days=1)):
        with pytest.raises(FinalSettlementConflictError) as dated:
            record(case, return_command(case, refund, 100, returned_at=when))
        assert cause(dated) == ("55000", "The return is dated before the Refund or in the future")
    with pytest.raises(FinalSettlementInvalidError) as no_new_refund:
        record(
            case,
            return_command(case, refund, 100, settlement_refund(case, "security", 100), new=False),
        )
    assert cause(no_new_refund) == (
        "22023",
        "A post-settlement correction has one Refund method, reference note, recipient and "
        "agreement",
    )
    with pytest.raises(psycopg.Error) as malformed, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
            (
                case["prop"],
                case["human"],
                uuid4(),
                case["settlement"],
                Jsonb(
                    {
                        **return_command(case, refund, 100).refund_return(),
                        "recipient_customer_id": str(case["customer"]),
                    }
                ),
                REASON,
            ),
        )
    assert malformed.value.sqlstate == "22023"
    # An impossible date or an offset PostgreSQL refuses is invalid input too (review round 2).
    for impossible in ("2026-02-30T09:30:00+00:00", "2026-10-08T09:30:00+16:00"):
        with pytest.raises(psycopg.Error) as impossible_date, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (
                    case["prop"],
                    case["human"],
                    uuid4(),
                    case["settlement"],
                    Jsonb(
                        {
                            **return_command(case, refund, 100).refund_return(),
                            "returned_at": impossible,
                        }
                    ),
                    REASON,
                ),
            )
        assert (impossible_date.value.sqlstate, impossible_date.value.diag.message_primary) == (
            "22023",
            "Returned Refund correction input is invalid",
        ), impossible
    reused = return_command(case, refund, 1_000)
    first = record(case, reused)
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(reused, returned_amount_usd_cents=900))
    other = record(case, return_command(case, refund, 1_000))
    assert record(case, reused) == first
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
    lease = one(url, "SELECT lease_id FROM app.final_settlements WHERE id=%s", case["settlement"])[
        0
    ]
    with psycopg.connect(url) as holder:
        holder.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], first),
        )
        for query, value in (
            ("SELECT 1 FROM app.leases WHERE id=%s FOR UPDATE NOWAIT", lease),
            (
                "SELECT 1 FROM app.customer_credits WHERE id=%s FOR UPDATE NOWAIT",
                case["refund_credit"],
            ),
        ):
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
            ):
                waiting.execute(query, (value,))
    assert net(url, refund) == 1_000
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, other)
    assert state(url, other) == "PENDING"


def test_the_relaxed_refund_correction_check_accepts_nothing_else(
    migrated_database_url: str,
) -> None:
    """The Refund correction check accepts, for a correction's Refund, only the verified return of
    its own REFUND_RETURN correction: inside a correction confirmed by hand in the same transaction
    (no role can write it), a linked row with another amount, another actor, the one-call
    reference, another return date, another correction Refund, another method reference or other
    evidence than the draft's is refused; the draft's own row passes, but a second return in the
    same correction is refused; outside a correction a row under financial.approve is refused too.
    After a real return, no row reverses it, linked to a later correction or not, under either
    reference (review rounds 1 and 2). Each attempt rolls back and the drafts stay pending."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, person, human = case["refund"], case["person"], case["human"]
    rent, _ = rent_line(url, case["initial"])
    [other_paid] = confirm_refund(case, record_refund(case, refund_command(case, rent, 300)))[
        "refunds"
    ]
    other = UUID(str(other_paid["id"]))
    draft = record(case, return_command(case, refund, 300))
    returned_at = one(
        url,
        "SELECT (payload->'refund_return'->>'returned_at')::timestamptz FROM app.financial_drafts "
        "WHERE id=%s",
        draft,
    )[0]

    def hand_built(draft_id: UUID, statement: str, values: tuple[object, ...]) -> None:
        """The draft's correction confirmed by hand, one linked row, refused."""
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            found = connection.execute(BEGIN, (case["prop"], person, draft_id)).fetchone()
            assert found is not None
            connection.execute(
                "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)",
                (found[0], values[0]),
            )
            connection.execute(statement, values)
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "23514",
            ONLY_THROUGH,
        ), values

    approve = "financial.approve"
    attempts = (
        return_values(uuid4(), 200, person, approve, returned_at, refund),
        return_values(uuid4(), 300, human, approve, returned_at, refund),
        return_values(uuid4(), 300, person, "refunds.correct", returned_at, refund),
        return_values(
            uuid4(), 300, person, approve, returned_at + timedelta(microseconds=1), refund
        ),
        return_values(uuid4(), 300, person, approve, returned_at, other),
        # Review round 2: the draft's method and evidence references too.
        return_values(uuid4(), 300, person, approve, returned_at, refund, method="Other method"),
        return_values(uuid4(), 300, person, approve, returned_at, refund, evidence="Other proof"),
    )
    for values in attempts:
        hand_built(draft, RETURN_ROW, values)
    # The draft's own return passes the check inside its correction; a second return in the same
    # correction is refused (review round 2: one return per correction).
    with pytest.raises(psycopg.Error) as second_return, psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], person, draft)).fetchone()
        assert found is not None
        for _ in range(2):
            row = uuid4()
            connection.execute(
                "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)",
                (found[0], row),
            )
            connection.execute(
                RETURN_ROW, return_values(row, 300, person, approve, returned_at, refund)
            )
            assert connection.execute(
                "SELECT app.refund_net_value_at(%s,'infinity')", (refund,)
            ).fetchone() == (1_700,)
    assert (second_return.value.sqlstate, second_return.value.diag.message_primary) == (
        "23514",
        ONLY_THROUGH,
    )
    with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
        connection.execute(
            RETURN_ROW, return_values(uuid4(), 300, person, approve, returned_at, refund)
        )
    assert (unlinked.value.sqlstate, unlinked.value.diag.message_primary) == (
        "23514",
        ONLY_THROUGH,
    )
    assert state(url, draft) == "PENDING"
    assert (net(url, refund), net(url, other)) == (2_000, 300)
    # After the real return, no row reverses it.
    [first_return] = confirm(case, draft)["refund_corrections"]
    later = record(case, return_command(case, refund, 100))
    for reference in ("financial.approve", "refunds.corrections.reverse"):
        values = (uuid4(), person, reference, first_return["id"], refund)
        hand_built(later, REVERSAL_ROW, values)
        with pytest.raises(psycopg.Error) as alone, psycopg.connect(url) as connection:
            connection.execute(REVERSAL_ROW, values)
        assert (alone.value.sqlstate, alone.value.diag.message_primary) == (
            "23514",
            ONLY_THROUGH,
        ), reference
    assert state(url, later) == "PENDING"
    assert net(url, refund) == 1_700


def test_refund_return_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms a returned-Refund correction; no role calls
    the internal functions; the migration adds only its functions, changes only the four patched
    functions (each new body exactly the old one with its replacements, privileges, owner,
    SECURITY DEFINER and settings kept) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                expected = role == "prm_financial" and function in (RECORD, CONFIRM)
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (expected,), (function, role)
        for function in (RECORD, CONFIRM, *INTERNAL):
            assert connection.execute(
                "SELECT prosecdef,proconfig::text LIKE '%%search_path=pg_catalog%%' "
                "FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                (function,),
            ).fetchone() == (function != INTERNAL[5], True), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "20270204_192"
    revision = scripts.get_revision("20261111_107")
    assert revision is not None and revision.down_revision == "20261110_106"
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

    with _temporary_migration_database("settlement_refund_return") as temporary:
        alembic_command.upgrade(config, "20261110_106")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261111_107")
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
