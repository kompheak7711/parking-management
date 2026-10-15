"""Post-settlement correction: a tie in the newest-first order of a correction's payments is broken
by write order (sub-slice 10e-3d-2b-3).

Owner answer (a) to Q-2026-10-14-111: within the newest-first order of one correction's payments
from a Credit or a Deposit, a tie in time is broken by the order the correction wrote them (its
effect sequence, the higher the newer), then by the id, so a correction gives the same result every
time. The database refuses a Credit application that is not later than every earlier event of its
Credit (`app.validate_credit_application_source`), so on the real path two payments of one source
never share a time (the first part of each test shows it); the tie is made by hand on the payments
of a real correction, in a transaction the table owner always rolls back, with the write order set
against the id order, so that the id alone would choose the other payment. A Deposit payment
also ranks by its `application_order`, unique per Final Settlement, so a Deposit tie needs that
constraint dropped too inside the rolled-back transaction (sub-slice 10e-3d-2c, independent review
round 1 set-up; the 10e-3d-2b-3 text said a Deposit tie could not be made even by hand).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_held_value_refund_migration import return_only
from test_settlement_refund_correction_migration import third_party_payment, unpaid_charge
from test_settlement_refund_return_migration import confirm, record, refunded_case, return_command
from test_settlement_return_reversal_migration import app_catalog

REVISION = "20261209_135"
PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"


def payments_in(
    connection: psycopg.Connection[Any], correction: object, credit: object
) -> list[tuple[str, int, int, Any]]:
    """The correction's payments from the Credit in the order it wrote them: id, amount, effect
    sequence and time."""
    found = connection.execute(
        "SELECT application.id::text,application.amount_usd_cents,effect.effect_sequence,"
        "application.occurred_at FROM app.settlement_correction_effects effect "
        "JOIN app.customer_credit_applications application "
        "ON application.id=effect.customer_credit_application_id "
        "WHERE effect.settlement_correction_id=%s AND application.customer_credit_id=%s "
        "ORDER BY effect.effect_sequence",
        (correction, credit),
    ).fetchall()
    return [(str(row[0]), int(row[1]), int(row[2]), row[3]) for row in found]


def payments_of(url: str, correction: object, credit: object) -> list[tuple[str, int, int, Any]]:
    with psycopg.connect(url) as connection:
        return payments_in(connection, correction, credit)


@contextmanager
def tied_by_hand(
    url: str, correction: object, credit: object
) -> Iterator[tuple[psycopg.Connection[Any], str, str]]:
    """In an owner transaction that is always rolled back: the correction's two payments from the
    Credit share the time of the one it wrote last, and the payment with the lower id gets the
    highest effect sequence (written last), so write order and id order disagree. Yields the
    connection, that payment (newest by write order) and the other one. Afterwards every trigger
    of the two tables is enabled again and the real rows are unchanged."""
    before = payments_of(url, correction, credit)
    [(older, _, _, _), (newer, _, _, newer_at)] = before
    low, high = sorted((older, newer), key=lambda found: UUID(found).bytes)
    with psycopg.connect(url) as connection:
        try:
            for table in ("customer_credit_applications", "settlement_correction_effects"):
                connection.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER USER")
            connection.execute(
                "UPDATE app.customer_credit_applications SET occurred_at=%s WHERE id=%s",
                (newer_at, older),
            )
            connection.execute(
                "UPDATE app.settlement_correction_effects SET effect_sequence=(SELECT "
                "max(effect.effect_sequence)+1 FROM app.settlement_correction_effects effect "
                "WHERE effect.settlement_correction_id=%s) "
                "WHERE customer_credit_application_id=%s",
                (correction, low),
            )
            assert [
                (found[0], found[3]) for found in payments_in(connection, correction, credit)
            ] == [
                (high, newer_at),
                (low, newer_at),
            ]
            yield connection, low, high
        finally:
            connection.rollback()
    assert one(
        url,
        "SELECT count(*) FROM pg_catalog.pg_trigger trigger "
        "WHERE trigger.tgrelid IN ('app.customer_credit_applications'::regclass,"
        "'app.settlement_correction_effects'::regclass) AND NOT trigger.tgisinternal "
        "AND trigger.tgenabled<>'O'",
    ) == (0,)
    assert payments_of(url, correction, credit) == before


def placed_parts(
    connection: psycopg.Connection[Any], settlement: object, credit: object, earlier: object
) -> list[tuple[str, int, int]]:
    """The parts of the earlier return's money that other corrections paid out: record, part and
    the part's offset in the record."""
    found = connection.execute(
        "SELECT placed.record_id::text,placed.part_usd_cents,placed.offset_usd_cents "
        "FROM app.settlement_returned_value_placed(%s,'CREDIT',%s,%s,true) placed",
        (settlement, credit, earlier),
    ).fetchall()
    return sorted((str(row[0]), int(row[1]), int(row[2])) for row in found)


def followed_in(
    connection: psycopg.Connection[Any], settlement: object, credit: object, record: object
) -> list[tuple[str, int, int, int, str | None]]:
    """Where E's stretch of the record (from 500, 1,000 long) is now: record, amount, offset,
    part and open kind."""
    found = connection.execute(
        "SELECT follow.follow_record_id::text,follow.follow_amount_usd_cents,"
        "follow.follow_offset_usd_cents,follow.follow_part_usd_cents,follow.follow_open_kind "
        "FROM app.settlement_returned_value_follow(%s,'CREDIT',%s,'CREDIT_APPLICATION',%s,500,"
        "1000) follow",
        (settlement, credit, record),
    ).fetchall()
    return sorted((str(row[0]), int(row[1]), int(row[2]), int(row[3]), row[4]) for row in found)


def source_of(
    connection: psycopg.Connection[Any], settlement: object, earlier: object
) -> dict[str, Any]:
    [found] = connection.execute(
        "SELECT app.settlement_return_reversal_source_state(%s,%s)", (settlement, earlier)
    ).fetchone() or (None,)
    assert isinstance(found, dict)
    return found


def listed(source: dict[str, Any]) -> list[str]:
    """The Credit payments the reversal lists, in the order it reverses them (newest first)."""
    return [str(item["id"]) for item in source["credit_applications"]]


def own_choice(source: dict[str, Any]) -> tuple[list[str], list[tuple[str, int, int]]]:
    """The own payments the reversal lists (newest first) and the part it applies again."""
    return (
        listed(source),
        [
            (str(item["application_id"]), item["reversed_usd_cents"], item["amount_usd_cents"])
            for item in source["reapply"]
        ],
    )


def swept_parts(source: dict[str, Any]) -> list[tuple[str, int]]:
    return sorted((str(item["record_id"]), item["part_usd_cents"]) for item in source["swept"])


def test_a_tie_in_time_is_broken_by_the_order_the_correction_wrote_its_payments(
    migrated_database_url: str,
) -> None:
    """Credit form, the placed parts. E brings back 1,000 (return only). A third party pays 800 of
    a first 1,500 charge; S brings back 500 (return only) and its step lets the Credit pay the
    first charge's other 700, then 800 of a second 1,500 charge, so S's draw is its own 500, then
    E's 1,000. On the real path S's second payment is stamped later and written later: newest
    first it is the 800 payment, so E's money is 300 of it (from 500) and the whole 700 payment,
    E's reversal lists the 800 payment first, and S's own reversal would reverse the 800 payment
    whole and put 300 back.

    Then, by hand, the two payments share one time and the payment with the lower id gets the
    higher effect sequence (written last), so write order and id order disagree. Newest first is
    now the payment written last: E's parts, the order E's reversal lists them in and S's own
    choice follow it, the same on a second read, and differ from what the id alone would
    choose."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, settlement = case["refund"], case["refund_credit"], case["settlement"]
    earlier = return_only(case, refund, 1_000)
    first_invoice, first_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, first_invoice, first_line, 800)
    _, second_line = unpaid_charge(url, case, case["person"])
    taker = return_only(
        case,
        refund,
        500,
        SettlementCreditStep(credit, LINE, first_line, 700),
        SettlementCreditStep(credit, LINE, second_line, 800),
    )
    [(older, older_amount, _, older_at), (newer, newer_amount, _, newer_at)] = payments_of(
        url, taker, credit
    )
    # The real path: two payments of one source never share a time.
    assert (older_amount, newer_amount) == (700, 800) and older_at < newer_at
    with psycopg.connect(url) as connection:
        assert placed_parts(connection, settlement, credit, earlier) == sorted(
            [(newer, 300, 500), (older, 700, 0)]
        )
        source = source_of(connection, settlement, earlier)
        assert (swept_parts(source), listed(source)) == (
            sorted([(newer, 300), (older, 700)]),
            [newer, older],
        )
        assert own_choice(source_of(connection, settlement, taker)) == (
            [newer],
            [(newer, 800, 300)],
        )
    amounts = {older: older_amount, newer: newer_amount}
    with tied_by_hand(url, taker, credit) as (connection, low, high):
        # Newest first by write order (the low id written last), and by the id alone.
        by_write = sorted([(low, amounts[low] - 500, 500), (high, amounts[high], 0)])
        by_id = sorted([(high, amounts[high] - 500, 500), (low, amounts[low], 0)])
        assert by_write != by_id
        for _ in range(2):
            assert placed_parts(connection, settlement, credit, earlier) == by_write
            source = source_of(connection, settlement, earlier)
            assert (swept_parts(source), listed(source)) == (
                [(record, part) for record, part, _ in by_write],
                [low, high],
            )
            assert own_choice(source_of(connection, settlement, taker)) == (
                [low],
                [(low, amounts[low], amounts[low] - 500)],
            )


def test_a_tie_in_a_changing_correction_s_payments_is_broken_by_write_order(
    migrated_database_url: str,
) -> None:
    """Credit form, the follow function (review round 1 set-up of the independent reviewer). E
    brings back 1,000 (return only); S brings back 500 (return only) and its step lets the Credit
    pay a 1,500 charge in one payment P (S's own 500, then E's 1,000). A third party pays 1,000 and
    800 of two later 1,500 charges. A Refund correction Q releases P whole: the released Credit
    pays the two other charges' 500 and 700 again (in that order) and Q refunds 300. Of the 1,500
    Q took back, its Refund pays out the first 300, then its payments newest first: on the real
    path the 700 payment, then the 500 one, so E's stretch of P (from 500) is 500 of the 700
    payment (from 200) and the whole 500 payment, and E's reversal lists the 700 payment first.

    Then, by hand, Q's two payments share one time and the lower id is written last: E's stretch
    follows the write order, the same on a second read, not the id."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, settlement = case["refund"], case["refund_credit"], case["settlement"]
    earlier = return_only(case, refund, 1_000)
    _, paid_line = unpaid_charge(url, case, case["person"])
    taker = return_only(case, refund, 500, SettlementCreditStep(credit, LINE, paid_line, 1_500))
    [(paying, _, _, _)] = payments_of(url, taker, credit)
    second_invoice, second_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, second_invoice, second_line, 1_000)
    third_invoice, third_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, third_invoice, third_line, 800)
    released = confirm_refund(
        case,
        record_refund(
            case,
            refund_command(
                case,
                paid_line,
                1_500,
                SettlementCreditStep(credit, LINE, second_line, 500),
                SettlementCreditStep(credit, LINE, third_line, 700),
            ),
        ),
    )
    changer = released["settlement_correction"]["id"]
    [paid] = released["refunds"]
    assert paid["amount_usd_cents"] == 300
    [(first, first_amount, _, first_at), (second, second_amount, _, second_at)] = payments_of(
        url, changer, credit
    )
    assert (first_amount, second_amount) == (500, 700) and first_at < second_at
    with psycopg.connect(url) as connection:
        assert followed_in(connection, settlement, credit, paying) == sorted(
            [(second, 700, 200, 500, None), (first, 500, 0, 500, None)]
        )
        source = source_of(connection, settlement, earlier)
        assert (swept_parts(source), listed(source)) == (
            sorted([(second, 500), (first, 500)]),
            [second, first],
        )
        assert source["swept_open"] == []
    amounts = {first: first_amount, second: second_amount}
    with tied_by_hand(url, changer, credit) as (connection, low, high):
        # After Q's 300 Refund: by write order the low id, then the high one; by the id alone the
        # other way round.
        by_write = sorted(
            [
                (low, amounts[low], 200, amounts[low] - 200, None),
                (high, amounts[high], 0, amounts[high], None),
            ]
        )
        by_id = sorted(
            [
                (high, amounts[high], 200, amounts[high] - 200, None),
                (low, amounts[low], 0, amounts[low], None),
            ]
        )
        assert by_write != by_id
        for _ in range(2):
            assert followed_in(connection, settlement, credit, paying) == by_write
            source = source_of(connection, settlement, earlier)
            assert (swept_parts(source), listed(source)) == (
                [(record, part) for record, _, _, part, _ in by_write],
                [low, high],
            )


def test_a_deposit_tie_made_by_hand_is_broken_by_write_order(migrated_database_url: str) -> None:
    """Sub-slice 10e-3d-2c (independent review round 1 set-up, Pet Deposit): E brings back 1,000
    of the Settlement's Pet Deposit Refund (return only); S brings back 700 and pays 300 of a 400
    debt from the Customer's Credit, the other 100 and a 1,500 debt from the Pet Deposit, and
    refunds 100, so E's 1,000 lies after S's own 700 across S's two Deposit payments. In an always
    rolled-back owner transaction the older payment takes the newer one's time and application
    order (the unique constraint dropped inside it) and the payment with the lower id is written
    last: E's placed parts follow the write order, not the id; afterwards the constraint, every
    trigger and the rows are as before."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    earlier = return_only(case, pet_paid, 1_000)
    invoice_a, line_a = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, invoice_a, line_a, 1_100)
    _, line_b = unpaid_charge(url, case, case["person"])
    taking = confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                700,
                SettlementCreditStep(case["new_credit"], LINE, line_a, 300),
                SettlementDepositStep(PET_REST, pet, LINE, line_a, 100),
                SettlementDepositStep(PET_REST, pet, LINE, line_b, 1_500),
                settlement_refund(case, "pet", 100),
                pet_remainder=STAFF,
            ),
        ),
    )
    correction = taking["settlement_correction"]["id"]
    rows = (
        "SELECT application.id::text,application.amount_usd_cents,application.occurred_at,"
        "application.application_order FROM app.settlement_correction_effects effect "
        "JOIN app.deposit_applications application ON application.id=effect.deposit_application_id "
        "WHERE effect.settlement_correction_id=%s ORDER BY effect.effect_sequence"
    )
    parts = (
        "SELECT placed.record_id::text,placed.part_usd_cents "
        "FROM app.settlement_returned_value_placed(%s,'DEPOSIT',%s,%s,true) placed "
        "WHERE placed.record_kind='DEPOSIT_APPLICATION'"
    )
    triggers = (
        "SELECT trigger.tgrelid::regclass::text,trigger.tgname,trigger.tgenabled "
        "FROM pg_catalog.pg_trigger trigger WHERE trigger.tgrelid IN "
        "('app.deposit_applications'::regclass,'app.settlement_correction_effects'::regclass) "
        "AND NOT trigger.tgisinternal ORDER BY 1,2"
    )
    with psycopg.connect(url) as connection:
        before = connection.execute(rows, (correction,)).fetchall()
        trigger_states = connection.execute(triggers).fetchall()
    [(older, _, _, _), (newer, _, newer_at, newer_order)] = before
    amounts = {str(row[0]): int(row[1]) for row in before}
    low, high = sorted((older, newer), key=lambda found: UUID(found).bytes)

    def expected(newest: str, other: str) -> list[tuple[str, int]]:
        """E's stretch [700, 1,700) over S's records: the 100 Refund first, then the newest."""
        found: list[tuple[str, int]] = []
        start = 100
        for record_id in (newest, other):
            end = start + amounts[record_id]
            part = min(end, 1_700) - max(start, 700)
            if part > 0:
                found.append((record_id, part))
            start = end
        return sorted(found)

    assert expected(low, high) != expected(high, low)
    with psycopg.connect(url) as connection:
        try:
            for table in ("deposit_applications", "settlement_correction_effects"):
                connection.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER USER")
            connection.execute(
                "ALTER TABLE app.deposit_applications "
                "DROP CONSTRAINT deposit_applications_settlement_order"
            )
            connection.execute(
                "UPDATE app.deposit_applications SET occurred_at=%s,application_order=%s "
                "WHERE id=%s",
                (newer_at, newer_order, older),
            )
            connection.execute(
                "UPDATE app.settlement_correction_effects SET effect_sequence=(SELECT "
                "max(effect.effect_sequence)+1 FROM app.settlement_correction_effects effect "
                "WHERE effect.settlement_correction_id=%s) WHERE deposit_application_id=%s",
                (correction, low),
            )
            tied = connection.execute(rows, (correction,)).fetchall()
            assert {(row[2], row[3]) for row in tied} == {(newer_at, newer_order)}
            for _ in range(2):
                found = connection.execute(parts, (case["settlement"], pet, earlier)).fetchall()
                assert sorted((str(row[0]), int(row[1])) for row in found) == expected(low, high)
        finally:
            connection.rollback()
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_constraint "
            "WHERE conname='deposit_applications_settlement_order'"
        ).fetchone() == (1,)
        assert connection.execute(triggers).fetchall() == trigger_states
        assert connection.execute(rows, (correction,)).fetchall() == before


def test_the_tie_break_changes_only_three_orders_and_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 135 adds no function, constraint or trigger; it changes only the placed, follow
    and return reversal source functions (each body exactly the old one with the module's
    replacements; privileges, owner, definer and settings kept, no role may call them), and is
    forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (PLACED, FOLLOW, SOURCE):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261208_134"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_returned_value_tie_break") as temporary:
        alembic_command.upgrade(config, "20261208_134")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PLACED, FOLLOW, SOURCE}
    patched = dict(revision.module.PATCHES)
    assert set(patched) == {PLACED, FOLLOW, SOURCE}
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, name
            assert "effect_sequence" in replacement and "effect_sequence" not in anchor
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
