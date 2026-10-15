"""Post-settlement correction: a return's money that left through a bounced Payment or a wrong
receipt is charged to the person who received the returned Refund (sub-slice 10e-3d-2c).

Owner answer (a) to Q-2026-10-13-103 point 1 (the Q-2026-10-11-78 rule: the person who received
the refund money pays it back). A `RETURNED_PAYMENT` correction or a `DEPOSIT_RECEIPT_CORRECTION`
C recovers every Refund paid from the money it takes back, reverses the payments made from it and
then reverses the source (the Credit, or the receipt into the Deposit). So money of an earlier
return-only correction E that was in the source, or that C brought back into it from another
correction's (or one of E's own uses') payment or Refund, left with C's reversal of the source,
while C charged E's returned Refund R's recipient only R's net, which E had lowered. E's reversal
charges each such part to R's recipient, and nothing else. The owner's two examples are the renamed
committed test of `test_settlement_returned_value_left_migration.py`:
`test_a_payment_return_and_a_receipt_correction_take_a_return_s_money_its_reversal_charges_back`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
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
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_receipt_correction_migration import confirm as confirm_receipt
from test_settlement_deposit_receipt_correction_migration import receipt_of
from test_settlement_deposit_receipt_correction_migration import record as record_receipt
from test_settlement_deposit_receipt_correction_migration import request as receipt_request
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import third_party_payment, unpaid_charge
from test_settlement_refund_return_migration import (
    BEGIN,
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
)
from test_settlement_return_reversal_changed_payment_migration import followed
from test_settlement_return_reversal_migration import (
    EVIDENCE,
    NOT_AVAILABLE,
    REASON,
    RECOVER,
    REVERSE_RETURN,
    app_catalog,
    confirm_reversal,
    correction_of,
    draft_source,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_payment_migration import command as returned_command
from test_settlement_returned_payment_migration import confirm as confirm_returned
from test_settlement_returned_payment_migration import credit_payment
from test_settlement_returned_payment_migration import record as record_returned
from test_settlement_returned_value_left_migration import (
    CHANGED,
    DRAFTS,
    INCOMPLETE,
    REVERSED,
    charged_back,
)

REVISION = "20261210_136"
CHARGE_BACK = "app.settlement_return_reversal_charge_back(app.refund_corrections)"
PAIRED = "app.settlement_return_reversal_paired_charge_back(app.refund_corrections)"
PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
GENERAL = "app.validate_general_refund_correction()"
WRITER = (
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)"
)
OWN_RETURN = "A Refund paid from the returned value has its own return; reverse that return first"
STATE = "SELECT app.settlement_return_reversal_source_state(%s,%s)"
LINK = "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)"
CHARGED = (
    "SELECT app.settlement_return_reversal_charge_back(correction) "
    "FROM app.refund_corrections correction WHERE correction.id=%s"
)
HISTORY = "Refund correction must continue exact source history"
# Security review round 2: a reversal row at a given time, and the latest time of a Refund's
# history as the general Refund correction check reads it.
REVERSE_AT = (
    "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,"
    "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
    "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,"
    "occurred_at,actor_id,authorization_reference) "
    "SELECT %s,original.refund_id,'CORRECTION_REVERSAL',original.id,"
    "-original.source_balance_effect_usd_cents,-original.source_balance_effect_usd_cents,"
    "app.refund_net_value_at(original.refund_id,'infinity'),"
    "app.refund_net_value_at(original.refund_id,'infinity')"
    "+original.source_balance_effect_usd_cents,"
    "%s,%s,%s,%s,'refunds.corrections.reverse' "
    "FROM app.refund_corrections original WHERE original.id=%s"
)
LATEST = (
    "SELECT GREATEST(refund.processed_at,(SELECT max(correction.occurred_at) "
    "FROM app.refund_corrections correction WHERE correction.refund_id=refund.id),"
    "app.credit_latest_at(refund.source_customer_credit_id),"
    "app.deposit_balance_latest_at(refund.source_deposit_id)) "
    "FROM app.refunds refund WHERE refund.id=%s"
)
PAIRED_ROW = (
    "SELECT app.settlement_return_reversal_paired_charge_back("
    "jsonb_populate_record(NULL::app.refund_corrections,%s))"
)


def returned_payment(case: dict[str, Any], credit: UUID) -> dict[str, Any]:
    """The bounced Payment behind the Credit, returned by a RETURNED_PAYMENT correction."""
    return confirm_returned(
        case, record_returned(case, returned_command(case, credit_payment(case["url"], credit)))
    )


def worked_example(url: str, back: int = 0) -> dict[str, Any]:
    """The design's worked example (Pet Deposit; both shapes through one receipt correction): E
    brings back 1,000 of the Settlement's Pet Deposit Refund (return only); a third party pays
    1,100 of a 1,500 charge; S brings back 100 with a new Refund: the Customer's Credit pays 300 of
    the 400 left (DL-032: Credit first), the Pet Deposit the other 100 and refunds 1,000, so E's
    1,000 sits from 100 in S's 1,000 Refund (900) and in all of S's 100 payment. The Pet Deposit's
    receipt is then found wrong: its DEPOSIT_RECEIPT_CORRECTION C charges S's Refund back (1,000)
    and the returned Refund's rest (4,300), reverses S's payment (the 100 is owed again) and the
    receipt. With `back`, that much of S's Refund comes back (return only) before C."""
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    earlier = return_only(case, pet_paid, 1_000)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, charge_invoice, charge_line, 1_100)
    assert outstanding(url, charge_line) == 400
    paid_out = confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                100,
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 100),
                settlement_refund(case, "pet", 1_000),
                pet_remainder=STAFF,
            ),
        ),
    )
    [paying] = paid_out["deposit_applications"]
    [refunded] = paid_out["refunds"]
    assert (held(url, pet), outstanding(url, charge_line)) == (0, 0)
    if back:
        return_only(case, refunded["id"], back)
    corrected = confirm_receipt(
        case, record_receipt(case, receipt_request(case, receipt_of(url, pet)))
    )
    assert (held(url, pet), net(url, refunded["id"]), net(url, pet_paid)) == (0, 0, 0)
    return {
        **case,
        "pet_paid": pet_paid,
        "earlier": earlier,
        "charge_line": charge_line,
        "paying": paying["id"],
        "refunded": refunded["id"],
        "corrected": correction_of(corrected),
    }


def state_in(connection: psycopg.Connection[Any], settlement: object, earlier: object) -> Any:
    """The return reversal source read inside the given transaction."""
    row = connection.execute(STATE, (settlement, earlier)).fetchone()
    assert row is not None
    return row[0]


def open_parts(source: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
    """The parts a source lists as open: kind, record, part, sorted."""
    return sorted(
        (item["kind"], item["record_id"], item["part_usd_cents"]) for item in source["swept_open"]
    )


@contextmanager
def by_hand(url: str, *tables: str) -> Iterator[psycopg.Connection[Any]]:
    """An owner transaction that is always rolled back, with the user triggers of the tables
    disabled only inside it; afterwards every trigger of the tables is in its earlier state."""
    triggers = (
        "SELECT trigger.tgname,trigger.tgenabled FROM pg_catalog.pg_trigger trigger "
        "WHERE trigger.tgrelid=ANY(%s::regclass[]) AND NOT trigger.tgisinternal "
        "ORDER BY trigger.tgname"
    )
    names = [f"app.{table}" for table in tables]
    with psycopg.connect(url) as connection:
        before = connection.execute(triggers, (names,)).fetchall()
    with psycopg.connect(url) as connection:
        try:
            for table in tables:
                connection.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER USER")
            yield connection
        finally:
            connection.rollback()
    with psycopg.connect(url) as connection:
        assert connection.execute(triggers, (names,)).fetchall() == before


def test_the_worked_example_charges_both_shapes_to_the_returned_refund_s_recipient(
    migrated_database_url: str,
) -> None:
    """The design's worked example: S's 100 payment that C reversed is followed to the returned
    Refund, and the 900 of S's Refund above its net (0, C charged all 1,000 back) is split off to
    it, so E's source lists one part of the returned Refund, 1,000, and E's reversal charges the
    1,000 to the person who received it: that person pays back 5,300 in total (the 5,400 Refund
    less S's real 100 return), S's Refund's recipient keeps C's 1,000 charge, and the 100 stays
    owed, as if E had never happened."""
    url = migrated_database_url
    case = worked_example(url)
    assert followed(
        url,
        case["settlement"],
        "DEPOSIT",
        case["pet"],
        "DEPOSIT_APPLICATION",
        case["paying"],
        0,
        100,
    ) == [("RETURNED_REFUND", None, None, 0, 100, None)]
    owed = outstanding(url, case["charge_line"])
    assert owed == 100
    charged_back(url, case, case["earlier"], case["pet_paid"], case["corrected"], 1_000, 5_300)
    assert (held(url, case["pet"]), outstanding(url, case["charge_line"])) == (0, owed)
    assert (net(url, case["refunded"]), net(url, case["pet_paid"])) == (0, 0)
    assert one(
        url,
        "SELECT sum(source_balance_effect_usd_cents) FROM app.refund_corrections "
        "WHERE refund_id=%s AND correction_kind='RECOVERED_BY_CHARGE'",
        case["refunded"],
    ) == (1_000,)


def test_an_own_use_s_payment_and_refund_that_a_bounced_payment_took_are_charged_back(
    migrated_database_url: str,
) -> None:
    """Credit form, the own uses: E brings back 1,800 of a correction's 2,000 Credit Refund; a
    held-value Refund naming E pays the Customer's 1,500 charge and refunds 300. The Payment
    behind the Credit bounces: its correction charges the returned Refund's 200 rest and the
    held-value Refund's 300 back, reverses the 1,500 payment (owed again) and the Credit. E's
    source takes the walk path (an own payment reversed since): the own payment is followed to the
    returned Refund (1,500) and the held-value Refund's 300 above its net is split off to it, so
    E's reversal charges 1,800 to the person who received the returned Refund (2,000 in total)."""
    url = migrated_database_url
    case = {**refunded_case(url), "url": url}
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 1_800)
    _, charge_line = unpaid_charge(url, case, case["person"])
    paid = confirm_held(
        case,
        record_held(
            case,
            held_command(case, earlier, SettlementCreditStep(credit, LINE, charge_line, 1_500)),
        ),
    )
    [held_refund] = paid["refunds"]
    assert held_refund["amount_usd_cents"] == 300
    returned = returned_payment(case, credit)
    assert (available(url, credit), net(url, held_refund["id"]), net(url, refund)) == (0, 0, 0)
    owed = outstanding(url, charge_line)
    assert owed == 1_500
    charged_back(url, case, earlier, refund, correction_of(returned), 1_800, 2_000, "own_parts")
    assert (available(url, credit), outstanding(url, charge_line)) == (0, owed)


def test_an_own_use_s_refund_that_a_bounced_payment_charged_back_takes_the_walk_path(
    migrated_database_url: str,
) -> None:
    """Credit form, an own Refund only (implementer's design change, review round 1): E brings
    back 300; a held-value Refund naming E refunds the 300 (no debt). The Payment bounces: its
    correction charges the held-value Refund and the returned Refund's 1,700 rest back and
    reverses the Credit. No own payment was reversed, but the own Refund that the bounced
    Payment's correction charged back sends E's source down the walk path, so its 300 above its
    net is split off to the returned Refund and charged to its recipient (2,000 in total)."""
    url = migrated_database_url
    case = {**refunded_case(url), "url": url}
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 300)
    paid = confirm_held(case, record_held(case, held_command(case, earlier)))
    [held_refund] = paid["refunds"]
    assert held_refund["amount_usd_cents"] == 300
    returned = returned_payment(case, credit)
    assert (available(url, credit), net(url, held_refund["id"]), net(url, refund)) == (0, 0, 0)
    charged_back(url, case, earlier, refund, correction_of(returned), 300, 2_000, "own_parts")


def test_the_returned_refund_parts_fail_closed(migrated_database_url: str) -> None:
    """Hand-built sources (the owner's Credit example: X1 300, then the bounced Payment): a part
    of the returned Refund without its recovery entry, with an entry of another amount, above its
    net, counting a return, two entries, or naming another Refund is incomplete; an entry counting
    a return is refused as before; an open part of the returned Refund is refused with the
    reworded message. By hand in an always rolled-back owner transaction: when the correction that
    took the money is of another kind, its Credit reversal stays an open take (Credit example) and,
    in the worked example, the payment it reversed and the Refund it charged back stay open; when
    the receipt correction did not also reverse the receipt, the follow function stops open at the
    payment it reversed."""
    url = migrated_database_url
    case = {**refunded_case(url), "url": url}
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 300)
    returned = returned_payment(case, credit)
    [source] = one(url, STATE, case["settlement"], earlier)
    [part] = source["swept"]
    [entry] = source["recoveries"]
    assert (part["record_kind"], entry["amount_usd_cents"], entry["net_usd_cents"]) == (
        "RETURNED_REFUND",
        300,
        300,
    )
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
    for built, message in (
        ({**source, "recoveries": []}, INCOMPLETE),
        ({**source, "recoveries": [{**entry, "amount_usd_cents": 299}]}, INCOMPLETE),
        ({**source, "recoveries": [{**entry, "net_usd_cents": 299}]}, INCOMPLETE),
        ({**source, "recoveries": [entry, entry]}, INCOMPLETE),
        ({**source, "recoveries": [{**entry, "returns": 1}]}, OWN_RETURN),
        ({**source, "swept": [{**part, "record_id": str(uuid4())}]}, INCOMPLETE),
        (
            {
                **source,
                "swept": [],
                "swept_undone_usd_cents": 0,
                "recoveries": [],
                "swept_open": [
                    {
                        "settlement_correction_id": part["settlement_correction_id"],
                        "kind": "RETURNED_REFUND",
                        "record_kind": "RETURNED_REFUND",
                        "record_id": part["record_id"],
                        "part_usd_cents": 300,
                    }
                ],
            },
            REVERSED,
        ),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), built
    other_kind = (
        "UPDATE app.financial_drafts SET payload=jsonb_set(payload,'{variant}','\"REFUND\"') "
        "WHERE id=(SELECT correlation_id FROM app.settlement_corrections WHERE id=%s)"
    )
    with by_hand(url, "financial_drafts") as connection:
        connection.execute(other_kind, (correction_of(returned),))
        opened = state_in(connection, case["settlement"], earlier)
        assert (opened["swept"], opened["recoveries"]) == ([], [])
        assert [(item["kind"], item["part_usd_cents"]) for item in opened["swept_open"]] == [
            ("CREDIT_REVERSAL", 300)
        ]
    # Independent review round 1 (Q1 set-up): the returned Refund's value lowered by hand, so the
    # parts of it add up to more than its net once the return is reversed: the part stays open.
    with by_hand(url, "refunds") as connection:
        connection.execute(
            "UPDATE app.refunds SET usd_accounting_value_cents=usd_accounting_value_cents-100,"
            "refund_amount_minor=refund_amount_minor-100 WHERE id=%s",
            (refund,),
        )
        opened = state_in(connection, case["settlement"], earlier)
        assert (opened["swept"], opened["recoveries"]) == ([], [])
        assert [
            (item["kind"], item["record_kind"], item["record_id"], item["part_usd_cents"])
            for item in opened["swept_open"]
        ] == [("RETURNED_REFUND", "RETURNED_REFUND", str(refund), 300)]
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(check, (Jsonb(opened),))
        assert refused.value.diag.message_primary == REVERSED
    worked = worked_example(url)
    opens = sorted(
        [
            ("CHANGED_APPLICATION", worked["paying"], 100),
            ("CHANGED_REFUND", worked["refunded"], 900),
        ]
    )
    # Independent review round 1: the receipt correction of another Settlement neither passes
    # the payment on nor covers the Refund's excess.
    with by_hand(url, "settlement_corrections") as connection:
        connection.execute(
            "UPDATE app.settlement_corrections SET final_settlement_id=%s WHERE id=%s",
            (case["settlement"], worked["corrected"]),
        )
        opened = state_in(connection, worked["settlement"], worked["earlier"])
        assert open_parts(opened) == opens
    with by_hand(url, "financial_drafts") as connection:
        connection.execute(other_kind, (worked["corrected"],))
        opened = state_in(connection, worked["settlement"], worked["earlier"])
        assert (opened["swept"], opened["recoveries"]) == ([], [])
        assert sorted(
            (item["kind"], item["record_id"], item["part_usd_cents"])
            for item in opened["swept_open"]
        ) == sorted(
            [
                ("CHANGED_APPLICATION", worked["paying"], 100),
                ("CHANGED_REFUND", worked["refunded"], 900),
            ]
        )
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(check, (Jsonb(opened),))
        assert refused.value.diag.message_primary == CHANGED
    with by_hand(url, "settlement_correction_effects") as connection:
        connection.execute(
            "DELETE FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s AND deposit_receipt_reversal_id IS NOT NULL",
            (worked["corrected"],),
        )
        assert connection.execute(
            "SELECT follow.follow_record_kind,follow.follow_record_id::text,"
            "follow.follow_open_kind "
            "FROM app.settlement_returned_value_follow(%s,%s,%s,%s,%s,%s,%s) follow",
            (
                worked["settlement"],
                "DEPOSIT",
                worked["pet"],
                "DEPOSIT_APPLICATION",
                worked["paying"],
                0,
                100,
            ),
        ).fetchall() == [("DEPOSIT_APPLICATION", worked["paying"], "CHANGED_APPLICATION")]
        # Independent review round 1: nor does the source split off the Refund's excess.
        opened = state_in(connection, worked["settlement"], worked["earlier"])
        assert open_parts(opened) == opens


def test_a_refund_part_charged_back_only_in_part_stays_open(migrated_database_url: str) -> None:
    """Independent review round 1, on the real path: as the worked example, but 500 of S's 1,000
    Refund comes back (return only) before the receipt correction, which then charges S's Refund
    back only 500, less than the 900 of E's money above its net: that part stays open
    (CHANGED_REFUND) while S's payment part is still followed to the returned Refund (100), and
    E's reversal is refused, writing nothing."""
    url = migrated_database_url
    case = worked_example(url, back=500)
    [source] = one(url, STATE, case["settlement"], case["earlier"])
    assert [
        (item["record_kind"], item["record_id"], item["part_usd_cents"]) for item in source["swept"]
    ] == [("RETURNED_REFUND", str(case["pet_paid"]), 100)]
    assert [
        (item["kind"], item["record_id"], item["part_usd_cents"]) for item in source["swept_open"]
    ] == [("CHANGED_REFUND", case["refunded"], 900)]
    unchanged = one(url, DRAFTS)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_reversal(case, reversal_command(case, case["earlier"]))
    assert cause(refused) == ("55000", NOT_AVAILABLE)
    assert one(url, DRAFTS) == unchanged


def reversed_in(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    draft: object,
    return_id: object,
    part: int,
) -> tuple[Any, Any, Any]:
    """In the caller's transaction, as the confirm writes them: the correction header, then the
    reversal of the return, which the insert accepts because the draft lists the returned Refund's
    charge-back of `part`. Returns the correction, the reversal row and its time."""
    begun = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
    assert begun is not None
    reversal = uuid4()
    connection.execute(LINK, (begun[0], reversal))
    connection.execute(REVERSE_RETURN, (reversal, REASON, EVIDENCE, case["person"], return_id))
    assert connection.execute(CHARGED, (reversal,)).fetchone() == (part,)
    found = connection.execute(
        "SELECT occurred_at FROM app.refund_corrections WHERE id=%s", (reversal,)
    ).fetchone()
    assert found is not None
    return begun[0], reversal, found[0]


def refused_without_charge_back(
    url: str, case: dict[str, Any], draft: object, part: int
) -> tuple[str, str]:
    """The reversal of the draft's return without its charge-back, in an always rolled-back
    transaction: the error that the deferred checks raise at SET CONSTRAINTS ALL IMMEDIATE."""
    return_id = draft_source(url, UUID(str(draft)))["earlier"]["return_id"]
    with psycopg.connect(url) as connection:
        try:
            reversed_in(connection, case, draft, return_id, part)
            with pytest.raises(psycopg.Error) as unmatched:
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            connection.rollback()
    return (str(unmatched.value.sqlstate), str(unmatched.value.diag.message_primary))


def test_the_relaxed_refund_correction_checks_still_refuse(migrated_database_url: str) -> None:
    """Security review rounds 1 and 2 (the owner's Credit example: X1 brings back 300, then the
    Payment bounces; and the worked Deposit example). In owner transactions written as the confirm
    writes them and always rolled back: the reversal of the return is accepted at insert because
    the draft lists the returned Refund's charge-back, but without that charge-back the deferred
    Credit or Deposit history check refuses the transaction; the general check still refuses a
    reversal row at the latest time (not a paired charge-back) and a charge-back written before the
    reversal; a charge-back row is paired with the reversal only when it is a charge-back by the
    same actor, linked to the correction, on the returned Refund, at the reversal's exact time.
    After the real confirm, neither helper counts those rows outside their own transaction."""
    url = migrated_database_url
    case = {**refunded_case(url), "url": url}
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 300)
    returned_payment(case, credit)
    draft = record_reversal(case, reversal_command(case, earlier))
    assert refused_without_charge_back(url, case, draft, 300) == (
        "23514",
        "Credit historical availability exceeded",
    )
    worked = worked_example(url)
    worked_draft = record_reversal(worked, reversal_command(worked, worked["earlier"]))
    assert refused_without_charge_back(url, worked, worked_draft, 1_000) == (
        "23514",
        "Deposit historical held balance cannot be negative",
    )
    source = draft_source(url, draft)
    return_id = source["earlier"]["return_id"]
    with psycopg.connect(url) as connection:
        try:
            begun = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
            latest = connection.execute(LATEST, (refund,)).fetchone()
            assert begun is not None and latest is not None
            tied = uuid4()
            connection.execute(LINK, (begun[0], tied))
            with pytest.raises(psycopg.Error) as same_time:
                connection.execute(
                    REVERSE_AT, (tied, REASON, EVIDENCE, latest[0], case["person"], return_id)
                )
        finally:
            connection.rollback()
    assert (same_time.value.sqlstate, same_time.value.diag.message_primary) == ("23514", HISTORY)
    with psycopg.connect(url) as connection:
        try:
            correction, _, at = reversed_in(connection, case, draft, return_id, 300)
            evidence = {
                "variant": "RETURN_REVERSAL",
                "returned_refund_id": str(refund),
                "returned_refund_at": (at - timedelta(microseconds=1)).isoformat(),
            }
            with pytest.raises(psycopg.Error) as before:
                connection.execute(
                    RECOVER,
                    (
                        case["prop"],
                        case["person"],
                        draft,
                        correction,
                        Jsonb(source["recoveries"]),
                        REASON,
                        EVIDENCE,
                        Jsonb(evidence),
                    ),
                )
        finally:
            connection.rollback()
    assert (before.value.sqlstate, before.value.diag.message_primary) == ("23514", HISTORY)

    def paired(
        connection: psycopg.Connection[Any],
        row: object,
        refunded: object,
        at: Any,
        kind: str = "RECOVERED_BY_CHARGE",
        actor: object = case["person"],
    ) -> Any:
        found = connection.execute(
            PAIRED_ROW,
            (
                Jsonb(
                    {
                        "id": str(row),
                        "refund_id": str(refunded),
                        "correction_kind": kind,
                        "occurred_at": at.isoformat(),
                        "actor_id": str(actor),
                    }
                ),
            ),
        ).fetchone()
        assert found is not None
        return found[0]

    with psycopg.connect(url) as connection:
        try:
            correction, _, at = reversed_in(connection, case, draft, return_id, 300)
            linked = uuid4()
            connection.execute(LINK, (correction, linked))
            assert paired(connection, linked, refund, at) is True
            assert paired(connection, linked, uuid4(), at) is False
            assert paired(connection, linked, refund, at + timedelta(microseconds=1)) is False
            assert paired(connection, uuid4(), refund, at) is False
            assert paired(connection, linked, refund, at, kind="CORRECTION_REVERSAL") is False
            assert paired(connection, linked, refund, at, actor=uuid4()) is False
        finally:
            connection.rollback()
    result = confirm_reversal(case, draft)
    with psycopg.connect(url) as connection:
        [(reversed_row,), (charged_row,)] = connection.execute(
            "SELECT correction.id FROM app.settlement_correction_effects effect "
            "JOIN app.refund_corrections correction ON correction.id=effect.refund_correction_id "
            "WHERE effect.settlement_correction_id=%s AND correction.refund_id=%s "
            "ORDER BY effect.effect_sequence",
            (correction_of(result), refund),
        ).fetchall()
        assert connection.execute(CHARGED, (reversed_row,)).fetchone() == (0,)
        assert connection.execute(
            "SELECT app.settlement_return_reversal_paired_charge_back(correction) "
            "FROM app.refund_corrections correction WHERE correction.id=%s",
            (charged_row,),
        ).fetchone() == (False,)


def test_the_returned_refund_charge_back_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the two new charge-back functions, SECURITY DEFINER with the fixed search
    path; migration 136 adds only them, changes only the eight listed functions (each body
    exactly the old one with the module's replacements; privileges, owner, definer and settings
    kept), adds no constraint or trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (CHARGE_BACK, PAIRED, PLACED, FOLLOW, SOURCE, ASSERT, SCOPE):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
        for function in (CHARGE_BACK, PAIRED):
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261209_135"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_returned_refund") as temporary:
        alembic_command.upgrade(config, "20261209_135")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions) | {CHARGE_BACK, PAIRED}
    patched = dict(revision.module.PATCHES)
    assert set(patched) == {PLACED, FOLLOW, SOURCE, ASSERT, SCOPE, CONFIRM, GENERAL, WRITER}
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
