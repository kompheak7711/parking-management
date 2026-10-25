"""Real PostgreSQL coverage of the Payments page period read (V1-058 R5c-3a).

Each payment in the period is split by what it paid (Rent, Utilities, Services, late-payment
charges, Deposits, move-out charges, Customer Credit) and what is left; the cards add up to
what was received.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadService,
    receipt_lines,
    summarize_period,
)
from property_rental.receipt import ReceiptService, ReprintReceiptCommand
from property_rental.receive_payment import ReceivePaymentCommand
from test_credit_migration import actor
from test_final_settlement_migration import one
from test_invoice_migration import financial_database_url, runtime_database_url
from test_late_charge_payment_proposal_migration import CHARGE, RENT, two_months
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_receive_payment_migration import charge, invoice, receive, usd

REVISION = "20270220_208"
KINDS = ("RENT", "UTIL", "SVC", "LATE", "DEPOSIT", "MOVEOUT", "CREDIT")


def today(url: str) -> date:
    value = one(url, "SELECT (now() AT TIME ZONE 'Asia/Phnom_Penh')::date")[0]
    return cast(date, value)


def summary(case: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    reader = PaymentReadService(runtime_database_url())
    who = actor(case["human"], case["prop"], "payments.read")
    return cast(dict[str, Any], summarize_period(reader, case["prop"], start, end, actor=who))


def test_each_payment_is_split_by_what_it_paid_and_the_cards_add_up(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    day = today(url)
    # Other test files share the Property, so the totals are checked against what was there.
    start = summary(case, day - timedelta(days=1), day + timedelta(days=1))["totals"]
    ticks = (
        invoice(case["invoice"], RENT),
        charge(case["charge"], CHARGE),
        invoice(case["later"], RENT),
    )
    paid = receive(
        case, ReceivePaymentCommand(usd(case, 2 * RENT + CHARGE + 2_000), "OLDEST_FIRST", ticks)
    )
    result = summary(case, day - timedelta(days=1), day + timedelta(days=1))

    assert result["truncated"] is False
    [row] = [item for item in result["rows"] if item["payment_id"] == paid["payment"]["id"]]
    assert row["payment_id"] == paid["payment"]["id"]
    assert row["receipt_number"] == paid["receipt"]["receipt_number"]
    assert row["customer_id"] == str(case["customer"])
    assert row["status"] == "RECEIVED" and row["received_currency"] == "USD"
    assert row["usd_cents"] == 2 * RENT + CHARGE + 2_000
    assert row["left_usd_cents"] == 2_000
    assert row["kinds"]["LATE"] == CHARGE
    assert row["kinds"].get("RENT", 0) + row["kinds"].get("SVC", 0) == 2 * RENT
    assert sum(row["kinds"].values()) + row["left_usd_cents"] == row["usd_cents"]
    assert datetime.fromisoformat(row["received_at"]).utcoffset() is not None

    totals = result["totals"]
    assert totals["payments"] - start["payments"] == 1
    assert totals["received_usd_cents"] - start["received_usd_cents"] == row["usd_cents"]
    assert totals["left_usd_cents"] - start["left_usd_cents"] == 2_000
    assert totals["left_payments"] - start["left_payments"] == 1
    added = {
        kind: totals["kinds"][kind]["usd_cents"] - start["kinds"][kind]["usd_cents"]
        for kind in KINDS
    }
    assert sum(added.values()) + 2_000 == row["usd_cents"]
    assert added["LATE"] == CHARGE and added["DEPOSIT"] == 0
    assert totals["kinds"]["LATE"]["payments"] - start["kinds"]["LATE"]["payments"] == 1
    assert totals["riel_received_minor"] == start["riel_received_minor"]

    before = summary(case, day - timedelta(days=40), day - timedelta(days=30))
    assert before["rows"] == [] and before["totals"]["payments"] == 0


def test_the_period_read_is_bounded_and_needs_payments_read(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    day = today(url)
    earlier = summary(case, day, day)["totals"]["payments"]
    for amount, tick in (
        (RENT, invoice(case["invoice"], RENT)),
        (CHARGE, charge(case["charge"], CHARGE)),
    ):
        receive(case, ReceivePaymentCommand(usd(case, amount), "OLDEST_FIRST", (tick,)))
    with psycopg.connect(runtime_database_url()) as connection:
        value = connection.execute(
            "SELECT app.payments_period_summary(%s,%s,%s,%s,1)",
            (case["prop"], case["human"], day, day),
        ).fetchone()
        assert value is not None
        assert value[0]["truncated"] is True and len(value[0]["rows"]) == 1
        assert value[0]["totals"]["payments"] == earlier + 2
        for bad in (
            (day, day - timedelta(days=1), 10),
            (day - timedelta(days=732), day, 10),
            (day, day, 0),
            (day, day, 501),
        ):
            with pytest.raises(psycopg.Error) as caught:
                connection.execute(
                    "SELECT app.payments_period_summary(%s,%s,%s,%s,%s)",
                    (case["prop"], case["human"], *bad),
                )
            assert caught.value.sqlstate == "P4902"
            connection.rollback()

    reader = PaymentReadService(runtime_database_url())
    with pytest.raises(PaymentReadAuthorizationError):
        summarize_period(
            reader,
            case["prop"],
            day,
            day,
            actor=actor(case["human"], case["prop"], "payments.record"),
        )
    with pytest.raises(PaymentReadInvalidError):
        summarize_period(
            reader,
            case["prop"],
            day,
            day - timedelta(days=1),
            actor=actor(case["human"], case["prop"], "payments.read"),
        )
    target = "app.payments_period_summary(uuid,uuid,date,date,integer)"
    grants = tuple(
        one(url, "SELECT has_function_privilege(%s,%s,'EXECUTE')", role, target)[0]
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap")
    )
    assert grants == (True, True, False)


def test_the_receipt_lines_name_what_one_payment_paid(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    ticks = (
        invoice(case["invoice"], RENT),
        charge(case["charge"], CHARGE),
        invoice(case["later"], 500),
    )
    paid = receive(
        case, ReceivePaymentCommand(usd(case, RENT + CHARGE + 500), "OLDEST_FIRST", ticks)
    )
    reader = PaymentReadService(runtime_database_url())
    who = actor(case["human"], case["prop"], "receipts.read")
    payment = UUID(paid["payment"]["id"])
    result = cast(dict[str, Any], receipt_lines(reader, case["prop"], payment, actor=who))

    assert result["receipt_number"] == paid["receipt"]["receipt_number"]
    assert result["customer_id"] == str(case["customer"])
    assert result["reference"] == "Receipt book page 12"
    assert result["received_by"] and result["method_name"]
    assert result["usd_cents"] == RENT + CHARGE + 500
    assert result["system_rate_khr_per_usd"] is None
    assert [
        (line["kind"], line["invoice_id"], line["amount_usd_cents"]) for line in result["lines"]
    ] == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("LATE_PAYMENT_CHARGE", str(case["invoice"]), CHARGE),
        ("INVOICE", str(case["later"]), 500),
    ]
    assert result["left_usd_cents"] == 0
    assert sum(line["amount_usd_cents"] for line in result["lines"]) == result["usd_cents"]
    assert result["reprints"] == [] and result["reprint_count"] == 0

    printer = ReceiptService(runtime_database_url(), financial_database_url())
    printer.reprint(
        case["prop"],
        UUID(result["receipt_id"]),
        ReprintReceiptCommand(uuid4(), "The Customer lost the Receipt"),
        actor=actor(case["human"], case["prop"], "receipts.reprint"),
    )
    again = cast(dict[str, Any], receipt_lines(reader, case["prop"], payment, actor=who))
    [reprint] = again["reprints"]
    assert reprint["reason"] == "The Customer lost the Receipt" and reprint["reprinted_by"]
    assert again["reprint_count"] == 1

    with pytest.raises(PaymentReadNotFoundError):
        receipt_lines(reader, case["prop"], uuid4(), actor=who)
    # The app has one Property, so another Property's id is one that does not exist.
    other = uuid4()
    with pytest.raises(PaymentReadNotFoundError):
        receipt_lines(reader, other, payment, actor=actor(case["human"], other, "receipts.read"))
    with psycopg.connect(runtime_database_url()) as connection, pytest.raises(psycopg.Error):
        connection.execute(
            "SELECT app.payment_receipt_lines(%s,%s,%s)", (case["prop"], uuid4(), payment)
        )
    with pytest.raises(PaymentReadAuthorizationError):
        receipt_lines(
            reader, case["prop"], payment, actor=actor(case["human"], case["prop"], "payments.read")
        )
