"""A receipt correction gives back only a shared Deposit's shortfall (V1-056 sub-slice
10e-2b-4e-2b-2a).

Owner answer (a) to Q-2026-10-18-127 ("the receipt correction does the same") and owner answers
(a) to Q-2026-10-18-134 (newest first): after closure, when the corrected receipt's Deposit also
holds another Payment's active receipt, the DEPOSIT_RECEIPT_CORRECTION gives back the Deposit's
shortfall (the corrected receipt less what the Deposit holds) from its uses still in force, newest
first: the Settlement's Refund is charged back to its recipient, then the Settlement's Deposit
application is reversed (the debt comes back) with its kept part written again. The other
Payment's money stays where the closed Settlement put it. Every test runs on a real closure, to
the cent.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    deposit_receipt_recovery_line_id,
    settlement_correction_draft_id,
)
from test_final_settlement_draft_migration import LINE, PET_FIRST, SECURITY
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_payment_return_recovery_migration import charge
from test_payment_return_shared_deposit_migration import (
    NEGATIVE,
    RECOVERED,
    active_receipts,
    net,
    recoveries,
)
from test_pet_payback_restoration_refusal_migration import owner
from test_settlement_correction_migration import settlement_row
from test_settlement_correction_plan_migration import new_credit
from test_settlement_deposit_receipt_correction_migration import (
    STILL_HOLDS,
    allowed_check,
    available,
    confirm,
    payload,
    record,
    request,
    source_of,
)
from test_settlement_deposit_receipt_rewrite_migration import receipts_of, targets_check
from test_settlement_extra_charge_migration import cause
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import record as record_return
from test_settlement_refund_return_migration import return_command
from test_settlement_returned_payment_migration import reconciled, status
from test_settlement_returned_payment_shared_deposit_migration import (
    KEPT_ALLOWED,
    NOT_LISTED,
    shared_security_case,
)

REVISION = "20270103_160"
NEW = {"app.settlement_deposit_receipt_correction_shared(uuid,jsonb)"}
PATCHED = {
    "app.settlement_deposit_receipt_correction_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_deposit_receipt_correction_allowed(uuid,uuid,jsonb)",
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)",
    "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)",
    "app.settlement_shared_deposit_kept_application_allowed(uuid,app.deposit_applications)",
    "app.payment_return_shortfall_recovery_amount(app.refund_corrections)",
    "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)",
}
LINKS = (
    "authorized_nonrecurring_obligation_id",
    "invoice_id",
    "refund_correction_id",
    "deposit_application_reversal_id",
    "deposit_application_id",
    "deposit_receipt_reversal_id",
    "deposit_receipt_id",
)
SHARED_ENDS = (
    "The Deposit would not end holding only the other Payments' money after this receipt correction"
)
HOLDS_OTHER = (
    "The corrected receipt's Deposit would still hold other money after this correction; pay it "
    "out with a held-value Refund correction first"
)
PAYBACK_SHARED = (
    "A new receipt into a Deposit that also holds another Payment's money and the Customer's "
    "pay-back money is not supported"
)
STAGE_FIRST = (
    "A Deposit step of this plan comes before, in the DL-032 order, a Deposit application this "
    "correction writes again"
)
REPEATS_KEPT = (
    "A Deposit step of this plan repeats a Deposit application this correction writes again; "
    "split the step"
)
DEPENDENT = "Deposit receipt has active dependent financial history"
CREDIT_AFTER_KEPT = (
    "A Customer Credit step cannot follow a Deposit application this correction writes again; "
    "refund or apply the Customer's Credit first, or correct the receipt without new receipts"
)
SHARED_REVERSAL = (
    "SELECT app.payment_return_shared_receipt_reversal_allowed(reversal) "
    "FROM app.deposit_receipt_reversals reversal WHERE reversal.id=%s"
)


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order."""
    found = rows(
        url,
        f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
        correction,
    )
    return [LINKS[[item is not None for item in row].index(True)] for row in found]


def receipt_by(url: str, deposit: UUID, payment: UUID) -> UUID:
    return UUID(
        str(
            value(
                url,
                "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s AND payment_id=%s",
                deposit,
                payment,
            )
        )
    )


def settlement_uses(url: str, security: UUID) -> tuple[UUID, UUID]:
    """The closed Settlement's 7,900 Security Deposit Refund and its 12,100 application."""
    [refund] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.refunds WHERE source_deposit_id=%s", security)
    ]
    [applied] = [
        UUID(str(row[0]))
        for row in rows(
            url, "SELECT id FROM app.deposit_applications WHERE deposit_id=%s", security
        )
    ]
    return refund, applied


def test_a_shared_deposit_receipt_meant_for_rent_gives_back_only_its_shortfall(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-18-127 on the real path: the Security Deposit holds the
    Reservation Payment A's 10,000 and Payment B's 10,000; the Settlement applied 12,100 to the
    other damage line and refunded 7,900. A's receipt was meant for Rent. The Deposit holds 0, so
    its shortfall is 10,000; newest first the correction charges the 7,900 Refund back to the
    Customer on the Lease and reverses the 12,100 application, writing its kept 10,000 again;
    then it reverses A's receipt. The line owes 2,100, the Deposit holds 0, B's receipt stays
    applied, A stays RECEIVED with 10,000 more available, the closed Settlement row is unchanged
    and the ledger reconciles. Hand-built sources whose plan does not give back the shortfall on
    the live state are refused."""
    url = migrated_database_url
    case = shared_security_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first, second = case["first"], case["second"]
    receipt = receipt_by(url, security, first)
    settlement_refund_id, applied = settlement_uses(url, security)
    before_row = settlement_row(url, case["settlement"])
    before_available = available(url, first)
    draft = record(case, request(case, receipt))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["deposit_id"],
        plan["receipt_usd_cents"],
        plan["held_usd_cents"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["plain"],
    ) == (str(security), 10_000, 0, 10_000, 10_000, True)
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("REFUND", str(settlement_refund_id), 7_900, 7_900, 0),
        ("APPLICATION", str(applied), 12_100, 2_100, 10_000),
    ]
    [recovery] = source["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["amount_usd_cents"],
        recovery["net_usd_cents"],
        recovery["shortfall_share"],
    ) == (str(settlement_refund_id), 7_900, 7_900, True)
    assert allowed_check(url, case, source) == (None, None)

    def changed(edit: dict[str, Any]) -> dict[str, Any]:
        copy = cast(dict[str, Any], json.loads(json.dumps(source)))
        copy["shared_deposits"][0].update(edit)
        return copy

    for edit in (
        {"uses": [plan["uses"][0], {**plan["uses"][1], "undo_usd_cents": 2_000}]},
        {"give_back_usd_cents": 9_999},
        {"held_usd_cents": 1},
        {"receipt_usd_cents": 9_000},
        {"shortfall_usd_cents": 0},
        {"deposit_id": str(case["pet"])},
        {"plain": False},
        {"uses": [*plan["uses"], {"kind": "FORFEITURE", "id": str(uuid4()), "undo_usd_cents": 0}]},
    ):
        assert allowed_check(url, case, changed(edit)) == ("55000", SHARED_ENDS), edit
    for shared in ([], [plan, plan]):
        assert allowed_check(url, case, {**source, "shared_deposits": shared}) == (
            "55000",
            SHARED_ENDS,
        )
    # Without its plan the source meets the one-Payment rule, which this Deposit cannot meet.
    unplanned = {key: item for key, item in source.items() if key != "shared_deposits"}
    assert allowed_check(url, case, unplanned) == ("55000", STILL_HOLDS)
    # Review round 1 (security S2): inside a confirm that is rolled back, a second kept part and a
    # kept part of another amount, each linked to the correction, are refused by the table. (The
    # receipt binding of the reversal check is tested with three Payments below: review round 2.)
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.confirm_settlement_deposit_receipt_correction("
            "%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert found is not None
        inside = UUID(str(cast(dict[str, Any], found[0])["settlement_correction"]["id"]))
        for amount in (10_000, 9_999):
            again = uuid4()
            with pytest.raises(psycopg.Error) as refused, connection.transaction():
                # The confirm set its constraints immediate; the link is written before its row.
                connection.execute("SET CONSTRAINTS ALL DEFERRED")
                connection.execute(
                    "SELECT app.link_settlement_correction_effect(%s,'deposit_application_id',%s)",
                    (inside, again),
                )
                connection.execute(
                    "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,'SECURITY_EXPLICIT',"
                    "'INVOICE_LINE',%s,%s,(SELECT max(application_order)+1 "
                    "FROM app.deposit_applications WHERE final_settlement_id=%s),'Again')",
                    (
                        case["prop"],
                        case["person"],
                        case["settlement"],
                        again,
                        security,
                        other_line,
                        amount,
                        case["settlement"],
                    ),
                )
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "23514",
                NOT_LISTED,
            )
        connection.rollback()

    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == [
        "authorized_nonrecurring_obligation_id",
        "invoice_id",
        "refund_correction_id",
        "deposit_application_reversal_id",
        "deposit_application_id",
        "deposit_receipt_reversal_id",
    ]
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        7_900,
    )
    assert (recoveries(url, settlement_refund_id), net(url, settlement_refund_id)) == ([7_900], 0)
    [reversal] = result["deposit_application_reversal_ids"]
    assert (
        value(
            url,
            "SELECT deposit_application_id FROM app.deposit_application_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        == applied
    )
    [kept] = result["deposit_application_ids"]
    assert one(
        url,
        "SELECT deposit_id,application_stage,invoice_line_id,amount_usd_cents,actor_id,"
        "final_settlement_id FROM app.deposit_applications WHERE id=%s",
        UUID(str(kept)),
    ) == (security, "SECURITY_EXPLICIT", other_line, 10_000, case["person"], case["settlement"])
    assert result["new_deposit_receipts"] == [] and result["refund_ids"] == []
    assert (held(url, security), outstanding(url, other_line)) == (0, 2_100)
    assert active_receipts(url, security) == [second]
    assert (status(url, first), status(url, second)) == ("RECEIVED", "RECEIVED")
    assert available(url, first) == before_available + 10_000
    assert result["payment"]["available_usd_cents"] == before_available + 10_000
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)
    # The kept part passes its own check only as this correction's listed part.
    kept_id = UUID(str(kept))
    assert value(url, KEPT_ALLOWED, correction, "{}", kept_id) is True
    assert value(url, KEPT_ALLOWED, correction, '{"amount_usd_cents": 9999}', kept_id) is False
    assert value(url, KEPT_ALLOWED, uuid4(), "{}", kept_id) is False
    # The shared receipt reversal passes only inside its correction's transaction.
    assert value(url, SHARED_REVERSAL, UUID(str(result["deposit_receipt_reversal_id"]))) is False


def test_a_shared_deposit_receipt_for_the_wrong_amount_is_written_again_and_applied(
    migrated_database_url: str,
) -> None:
    """Owner rules 1 and 2 of Q-2026-10-12-87 on a shared Deposit: A's 10,000 receipt was really
    8,000 Security Deposit and 2,000 Rent. After the give-back above (the 7,900 charge back, 2,100
    of the application reversed), the correction writes an 8,000 receipt from A into the same
    Deposit and its DL-032 step applies 2,100 to the damage line and 5,900 to the recovery
    charge's placeholder line: 2,000 stays owed by the Customer and 2,000 with A. Inside the
    confirm, before it commits, the shared receipt reversal passes its check."""
    url = migrated_database_url
    case = shared_security_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first, second = case["first"], case["second"]
    receipt = receipt_by(url, security, first)
    settlement_refund_id, _ = settlement_uses(url, security)
    before_available = available(url, first)
    base = request(case, receipt, receipts=(CorrectionDepositReceipt(security, 8_000),))
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, settlement_refund_id)
    draft = record(
        case,
        replace(
            base,
            steps=(
                SettlementDepositStep(SECURITY, security, LINE, other_line, 2_100),
                SettlementDepositStep(SECURITY, security, LINE, placeholder, 5_900),
            ),
        ),
    )
    assert draft == draft_id
    stored = payload(url, draft)
    assert stored["plan_overlay"]["obligations"] == {f"INVOICE_LINE:{other_line}": 2_100}
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 8_000}
    assert stored["plan_overlay"]["new_obligations"] == {
        str(placeholder): {
            "refund_id": str(settlement_refund_id),
            "customer_id": str(customer),
            "lease_id": str(case["lease"]),
            "amount_usd_cents": 7_900,
        }
    }
    assert stored["plan_result"]["closing_balance_usd_cents"] == 2_000
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.confirm_settlement_deposit_receipt_correction("
            "%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert found is not None
        inside = cast(dict[str, Any], found[0])
        allowed = connection.execute(
            SHARED_REVERSAL, (UUID(str(inside["deposit_receipt_reversal_id"])),)
        ).fetchone()
        assert allowed is not None and allowed[0] is True
        connection.rollback()
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == [
        "authorized_nonrecurring_obligation_id",
        "invoice_id",
        "refund_correction_id",
        "deposit_application_reversal_id",
        "deposit_application_id",
        "deposit_receipt_reversal_id",
        "deposit_receipt_id",
        "deposit_application_id",
        "deposit_application_id",
    ]
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    [kept, on_line, on_charge] = [UUID(str(item)) for item in result["deposit_application_ids"]]
    recovery_line = UUID(
        str(
            value(
                url,
                "SELECT id FROM app.invoice_lines WHERE invoice_id=%s",
                UUID(str(recovered["invoice_id"])),
            )
        )
    )
    assert [
        one(
            url,
            "SELECT deposit_id,application_stage,invoice_line_id,amount_usd_cents "
            "FROM app.deposit_applications WHERE id=%s",
            application,
        )
        for application in (kept, on_line, on_charge)
    ] == [
        (security, "SECURITY_EXPLICIT", other_line, 10_000),
        (security, "SECURITY_EXPLICIT", other_line, 2_100),
        (security, "SECURITY_EXPLICIT", recovery_line, 5_900),
    ]
    assert (outstanding(url, other_line), outstanding(url, recovery_line)) == (0, 2_000)
    assert held(url, security) == 0
    assert receipts_of(url, security) == [
        (first, 10_000, True),
        (second, 10_000, False),
        (first, 8_000, False),
    ]
    assert (status(url, first), available(url, first)) == ("RECEIVED", before_available + 2_000)
    reconciled(url, customer)


@pytest.mark.parametrize("right", [False, True], ids=["no_right_receipt", "right_receipt"])
def test_a_receipt_correction_charges_back_only_part_of_a_refund_larger_than_its_shortfall(
    migrated_database_url: str, right: bool
) -> None:
    """Review round 1 (both reviewers' set-up): Payment B's receipt is 20,000, so the Settlement
    applied 12,100 and refunded 17,900. A's 10,000 receipt is corrected: its 10,000 shortfall comes
    from the newest use alone, the 17,900 Refund, which is charged back only in part (10,000; its
    net becomes 7,900); no application is reversed. That share passes the recovery insert check
    only through the receipt correction's shortfall branch, and the receipt reversal passes beside
    the Refund that stays out. With a right 8,000 receipt the plan pays 8,000 of the 10,000
    recovery charge's placeholder line, which then owes 2,000, and 2,000 stays with A."""
    url = migrated_database_url
    case = shared_security_case(url, 20_000)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first, second = case["first"], case["second"]
    receipt = receipt_by(url, security, first)
    settlement_refund_id, _ = settlement_uses(url, security)
    before_available = available(url, first)
    base = request(case, receipt)
    if right:
        draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
        placeholder = deposit_receipt_recovery_line_id(draft_id, settlement_refund_id)
        base = replace(
            base,
            receipts=(CorrectionDepositReceipt(security, 8_000),),
            steps=(SettlementDepositStep(SECURITY, security, LINE, placeholder, 8_000),),
        )
    draft = record(case, base)
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("REFUND", str(settlement_refund_id), 17_900, 10_000, 7_900)
    ]
    [recovery] = source["recoveries"]
    assert (
        recovery["amount_usd_cents"],
        recovery["net_usd_cents"],
        recovery["shortfall_share"],
    ) == (10_000, 17_900, True)
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    links = [
        "authorized_nonrecurring_obligation_id",
        "invoice_id",
        "refund_correction_id",
        "deposit_receipt_reversal_id",
    ]
    assert effect_links(url, correction) == links + (
        ["deposit_receipt_id", "deposit_application_id"] if right else []
    )
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "PARTIALLY_PAID" if right else "UNPAID",
        10_000,
    )
    assert (recoveries(url, settlement_refund_id), net(url, settlement_refund_id)) == (
        [10_000],
        7_900,
    )
    assert result["deposit_application_reversal_ids"] == []
    recovery_line = UUID(
        str(
            value(
                url,
                "SELECT id FROM app.invoice_lines WHERE invoice_id=%s",
                UUID(str(recovered["invoice_id"])),
            )
        )
    )
    assert (held(url, security), outstanding(url, other_line)) == (0, 0)
    assert outstanding(url, recovery_line) == (2_000 if right else 10_000)
    assert active_receipts(url, security) == ([second, first] if right else [second])
    assert (status(url, first), available(url, first)) == (
        "RECEIVED",
        before_available + (2_000 if right else 10_000),
    )
    reconciled(url, customer)


def test_a_plan_step_that_repeats_the_kept_part_is_refused_and_a_split_step_passes(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 1; its set-up): Payment B's receipt is 4,000, so the
    Settlement applied 12,100 and refunded 1,900; A's 10,000 shortfall takes the 1,900 Refund and
    8,100 of the application, whose kept 4,000 is written again. A right 4,000 receipt whose plan
    applies exactly 4,000 to the same line repeats the kept part, which the Deposit application
    check would count as that part at the confirm, so it is refused at record (55000). Applied as
    3,000 on the line and 1,000 on the recovery charge's placeholder line it passes: the line owes
    5,100, the recovery charge 900, the Deposit holds 0 and A has 6,000 more available."""
    url = migrated_database_url
    case = shared_security_case(url, 4_000)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first = case["first"]
    receipt = receipt_by(url, security, first)
    settlement_refund_id, _ = settlement_uses(url, security)
    before_available = available(url, first)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(security, 4_000),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 4_000),),
            ),
        )
    assert cause(refused) == ("55000", REPEATS_KEPT)
    base = request(case, receipt, receipts=(CorrectionDepositReceipt(security, 4_000),))
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, settlement_refund_id)
    draft = record(
        case,
        replace(
            base,
            steps=(
                SettlementDepositStep(SECURITY, security, LINE, other_line, 3_000),
                SettlementDepositStep(SECURITY, security, LINE, placeholder, 1_000),
            ),
        ),
    )
    [plan] = payload(url, draft)["source"]["shared_deposits"]
    keys = ("kind", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("REFUND", 1_900, 0),
        ("APPLICATION", 8_100, 4_000),
    ]
    result = confirm(case, draft)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    recovery_line = UUID(
        str(
            value(
                url,
                "SELECT id FROM app.invoice_lines WHERE invoice_id=%s",
                UUID(str(recovered["invoice_id"])),
            )
        )
    )
    assert [
        one(
            url,
            "SELECT invoice_line_id,amount_usd_cents FROM app.deposit_applications WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(other_line, 4_000), (other_line, 3_000), (recovery_line, 1_000)]
    assert (outstanding(url, other_line), outstanding(url, recovery_line)) == (5_100, 900)
    assert held(url, security) == 0
    assert available(url, first) == before_available + 6_000
    reconciled(url, customer)


def test_a_shared_deposit_holding_more_than_the_receipt_gives_back_nothing(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security note 6; its set-up): Payment B's receipt is 20,000; a return-only
    correction records the whole 17,900 Settlement Refund as returned, so the Deposit holds
    17,900, more than A's 10,000 receipt. With a right receipt the correction is refused at record
    (55000; the Deposit would still hold other money: a known limit). Without one, the shortfall
    is 0: nothing is recovered or reversed, A's receipt is reversed beside the active 12,100
    application, and the Deposit ends holding 7,900."""
    url = migrated_database_url
    case = shared_security_case(url, 20_000)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first, second = case["first"], case["second"]
    receipt = receipt_by(url, security, first)
    settlement_refund_id, applied = settlement_uses(url, security)
    confirm_return(
        case, record_return(case, return_command(case, settlement_refund_id, 17_900, new=False))
    )
    assert held(url, security) == 17_900
    before_available = available(url, first)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(security, 8_000),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000),),
            ),
        )
    assert cause(refused) == ("55000", HOLDS_OTHER)
    draft = record(case, request(case, receipt))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["held_usd_cents"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["uses"],
        source["recoveries"],
    ) == (17_900, 0, 0, [], [])
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == ["deposit_receipt_reversal_id"]
    assert (held(url, security), outstanding(url, other_line)) == (7_900, 0)
    assert (
        value(
            url,
            "SELECT count(*) FROM app.deposit_application_reversals "
            "WHERE deposit_application_id=%s",
            applied,
        )
        == 0
    )
    assert active_receipts(url, security) == [second]
    assert (status(url, first), available(url, first)) == ("RECEIVED", before_available + 10_000)
    reconciled(url, customer)


@pytest.mark.parametrize(
    ("share", "refusal"),
    [(10_001, RECOVERED), (9_999, NEGATIVE)],
    ids=["above_the_shortfall", "below_the_shortfall"],
)
def test_the_table_checks_hold_a_receipt_correction_share_to_the_shortfall(
    migrated_database_url: str, share: int, refusal: str
) -> None:
    """Review round 1 (security S2 b; hand-built in a rolled-back owner transaction, because no
    source the database builds reaches it): the shared plan is replaced so its recovery asks one
    cent more or less than the 10,000 shortfall of a 17,900 Refund (the record check compares the
    uses, not the recoveries, with the shortfall). One cent more is refused by the recovery insert
    check (23514); one cent less by the Deposit's held-history check when A's receipt is reversed
    (23514). Nothing is written."""
    url = migrated_database_url
    case = shared_security_case(url, 20_000)
    security, first, second = case["security"], case["first"], case["second"]
    receipt = receipt_by(url, security, first)
    with psycopg.connect(owner()) as connection:
        connection.execute(
            "CREATE OR REPLACE FUNCTION app.settlement_deposit_receipt_correction_shared("
            "p_property uuid,p_source jsonb) RETURNS jsonb LANGUAGE sql STABLE "
            "SECURITY DEFINER SET search_path=pg_catalog AS $$ "
            "SELECT jsonb_build_object('recoveries',(SELECT jsonb_agg(recovery"
            f"||jsonb_build_object('amount_usd_cents',{int(share)}::bigint)) "
            "FROM jsonb_array_elements(found.plan->'recoveries') recovery),"
            "'shared_deposits',(SELECT jsonb_agg(shared) "
            "FROM jsonb_array_elements(found.plan->'shared_deposits') shared "
            "WHERE shared->>'deposit_id'=p_source->'receipt'->>'deposit_id')) "
            "FROM (SELECT app.settlement_returned_payment_shared(p_property,"
            "(p_source->'receipt'->>'payment_id')::uuid,p_source) AS plan) found $$"
        )
        draft = uuid4()
        connection.execute(
            "SELECT app.record_settlement_deposit_receipt_correction_draft("
            "%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
            (
                case["prop"],
                case["human"],
                draft,
                case["settlement"],
                Jsonb({"deposit_receipt_id": str(receipt), "evidence_reference": "Bank line"}),
                "The receipt was meant for Rent",
            ),
        )
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            connection.execute(
                "SELECT app.confirm_settlement_deposit_receipt_correction("
                "%s,%s,%s,'financial.approve')",
                (case["prop"], case["person"], draft),
            )
        assert refused.value.diag.message_primary == refusal
        connection.rollback()
    assert (held(url, security), active_receipts(url, security)) == (0, [first, second])


def test_the_shared_receipt_reversal_check_binds_its_own_receipt_and_no_forfeiture(
    migrated_database_url: str,
) -> None:
    """Review round 2 (both reviewers' set-ups): a Security Deposit of three Payments (A 10,000,
    B 10,000, C 5,000); the Settlement applied 12,100 and refunded 12,900. A's correction charges
    back 10,000 of that Refund (its net becomes 2,900) and reverses A's receipt; the application
    stays. Inside the confirm, before it commits, the check passes for A's reversal; a reversal of
    B's receipt linked to the same correction is refused (55000) although C's receipt is still
    active, because the draft names only A's receipt; and beside a hand-built active forfeiture of
    the Deposit (its triggers switched off only in the rolled-back transaction) the check fails
    for A's reversal too. The real confirm then leaves B's and C's receipts and a Deposit at 0."""
    url = migrated_database_url
    case = shared_security_case(url, 10_000, 5_000)
    security, customer = case["security"], case["customer"]
    first, second, third = case["first"], case["second"], case["third"]
    receipt = receipt_by(url, security, first)
    other_receipt = receipt_by(url, security, second)
    settlement_refund_id, applied = settlement_uses(url, security)
    draft = record(case, request(case, receipt))
    [plan] = payload(url, draft)["source"]["shared_deposits"]
    keys = ("kind", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [("REFUND", 10_000, 2_900)]
    with psycopg.connect(owner()) as connection:
        found = connection.execute(
            "SELECT app.confirm_settlement_deposit_receipt_correction("
            "%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert found is not None
        inside = cast(dict[str, Any], found[0])
        correction = UUID(str(inside["settlement_correction"]["id"]))
        reversal = UUID(str(inside["deposit_receipt_reversal_id"]))
        allowed = connection.execute(SHARED_REVERSAL, (reversal,)).fetchone()
        assert allowed is not None and allowed[0] is True
        with pytest.raises(psycopg.Error) as other, connection.transaction():
            # Deferred, so only the insert check of the reversal can refuse it here.
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "SELECT app.write_payment_return_receipt_reversal(%s,%s,%s,%s,'Other',%s,%s,"
                "clock_timestamp())",
                (case["prop"], case["person"], correction, other_receipt, uuid4(), "0" * 64),
            )
        assert (other.value.sqlstate, other.value.diag.message_primary) == ("55000", DEPENDENT)
        connection.execute("ALTER TABLE app.deposit_dispositions DISABLE TRIGGER USER")
        connection.execute(
            "INSERT INTO app.deposit_dispositions(id,deposit_id,amount_usd_cents,"
            "governing_lease_id,effective_date,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (gen_random_uuid(),%s,1,%s,current_date,"
            "'Hand-built forfeiture',clock_timestamp(),%s,'deposits.dispose')",
            (security, case["lease"], case["human"]),
        )
        connection.execute("ALTER TABLE app.deposit_dispositions ENABLE TRIGGER USER")
        kept = connection.execute(SHARED_REVERSAL, (reversal,)).fetchone()
        assert kept is not None and kept[0] is False
        connection.rollback()
    result = confirm(case, draft)
    assert (recoveries(url, settlement_refund_id), net(url, settlement_refund_id)) == (
        [10_000],
        2_900,
    )
    assert result["deposit_application_reversal_ids"] == []
    assert (
        value(
            url,
            "SELECT count(*) FROM app.deposit_application_reversals "
            "WHERE deposit_application_id=%s",
            applied,
        )
        == 0
    )
    assert held(url, security) == 0
    assert active_receipts(url, security) == [second, third]
    forfeitures = "SELECT count(*) FROM app.deposit_dispositions WHERE deposit_id=%s"
    assert value(url, forfeitures, security) == 0
    reconciled(url, customer)


def test_a_customer_credit_step_beside_a_kept_part_is_refused_at_record(
    migrated_database_url: str,
) -> None:
    """Review round 2 (independent should-fix 1; its set-up): after closure the Customer has 1,000
    of new Credit, so the plan of A's right 8,000 receipt must use it first; but the correction
    writes the kept 10,000 application part before its plan, and the correction's Credit order
    check refuses Credit after its Deposit applications, so such a draft could never be
    confirmed. It is refused at record (55000, a known limit: staff apply the Credit to the open
    debt first) and nothing is written."""
    url = migrated_database_url
    case = shared_security_case(url)
    security, other_line = case["security"], case["other_line"]
    receipt = receipt_by(url, security, case["first"])
    settlement_refund_id, _ = settlement_uses(url, security)
    credit = new_credit(url, case, 1_000)
    base = request(case, receipt, receipts=(CorrectionDepositReceipt(security, 8_000),))
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, settlement_refund_id)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(
            case,
            replace(
                base,
                steps=(
                    SettlementCreditStep(credit, LINE, other_line, 1_000),
                    SettlementDepositStep(SECURITY, security, LINE, other_line, 1_100),
                    SettlementDepositStep(SECURITY, security, LINE, placeholder, 6_900),
                ),
            ),
        )
    assert cause(refused) == ("55000", CREDIT_AFTER_KEPT)
    assert value(url, "SELECT count(*) FROM app.financial_drafts WHERE id=%s", draft_id) == 0


def test_the_right_receipt_refusals_of_a_shared_deposit(migrated_database_url: str) -> None:
    """Fail-closed refusals on the shared path: a plan Deposit step whose DL-032 stage comes
    before the kept Security application part is refused at record time; on hand-built targets, a
    shared Deposit that would still hold other money after the correction, and a right receipt
    into a shared Deposit with a pay-back count, are refused (known limits)."""
    url = migrated_database_url
    case = shared_security_case(url)
    security, other_line = case["security"], case["other_line"]
    receipt = receipt_by(url, security, case["first"])
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(security, 8_000),),
                steps=(
                    SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 1),
                    SettlementDepositStep(SECURITY, security, LINE, other_line, 2_100),
                ),
            ),
        )
    assert cause(refused) == ("55000", STAGE_FIRST)
    source = source_of(url, case, receipt)
    receipts = [{"deposit_id": str(security), "amount_usd_cents": 8_000}]
    targets = cast(
        list[dict[str, Any]],
        value(
            url,
            "SELECT app.settlement_deposit_receipt_correction_targets(%s,%s,%s)",
            case["prop"],
            Jsonb(source),
            Jsonb(receipts),
        ),
    )
    assert targets_check(url, case, source, targets) == (None, None)
    holding = cast(dict[str, Any], json.loads(json.dumps(source)))
    holding["shared_deposits"][0]["held_usd_cents"] = 5_000
    assert targets_check(url, case, holding, targets) == ("55000", HOLDS_OTHER)
    del holding["shared_deposits"][0]["give_back_usd_cents"]
    holding["shared_deposits"][0]["held_usd_cents"] = 0
    assert targets_check(url, case, holding, targets) == ("55000", HOLDS_OTHER)
    counted = [{**targets[0], "payback_count": 1}]
    assert targets_check(url, case, source, counted) == ("55000", PAYBACK_SHARED)
    unshared = {k: v for k, v in source.items() if k != "shared_deposits"}
    assert targets_check(url, case, unshared, counted) == (None, None)


def test_the_shared_receipt_correction_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-2b-2a adds one internal function with no grant and patches only the
    listed functions, by exactly their listed replacements, with the same owner, privileges and
    settings; no constraint or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270102_159"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        others = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT 'constraint',c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app' AND c.contype<>'t' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("receipt_correction_shared_deposit") as temporary:
        alembic_command.upgrade(config, "20270102_159")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
        for function in NEW:
            for role in ("PUBLIC", "prm_runtime", "prm_financial", "prm_bootstrap"):
                grantee = "public" if role == "PUBLIC" else role
                assert (
                    value(
                        temporary,
                        "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                        grantee,
                        function,
                    )
                    is False
                ), (function, role)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions) | NEW
    assert after_functions[next(iter(NEW))][3:] == (True, "{search_path=pg_catalog,TimeZone=UTC}")
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for signature, replacements in revision.module.PATCHES:
        name = str(signature)
        expected = before_functions[name][0]
        for before, after in replacements:
            assert expected.count(before) == 1
            expected = expected.replace(before, after)
        assert after_functions[name][0] == expected
        assert after_functions[name][1:] == before_functions[name][1:]
