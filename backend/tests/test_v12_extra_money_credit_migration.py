"""Extra money becomes Customer Credit at once at Receive payment (D5, DL-235; BR-PAY-030).

Owner (12 Nov 2026, DL-226, D5). Before, money above everything the payer owed waited on the
Receipt until the payer chose Credit or a Refund. Now Receive payment makes it the payer's
Customer Credit in the same step; the Customer may ask for a Refund of that Credit any day.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

import psycopg

from property_rental.khr_payment_confirmation import ConfirmKhrPaymentCommand
from property_rental.receive_payment import ReceivePaymentCommand
from test_credit_migration import actor
from test_final_settlement_migration import one
from test_khr_payment_confirmation import provider
from test_late_charge_payment_proposal_migration import CHARGE, RENT, status, two_months
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_receive_payment_migration import charge, counts, invoice, receive, usd

KEPT = "Kept as Customer Credit at once by the rule (BR-PAY-030, DL-235)"
REASON = "Money above everything owed at Receive payment."


def credits(url: str, payment_id: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT customer_id,recognized_usd_cents,customer_authorization_reference,reason "
            "FROM app.customer_credits WHERE source_payment_id=%s ORDER BY recognized_at",
            (str(payment_id),),
        ).fetchall()


def left(url: str, payment_id: object) -> int:
    return int(one(url, "SELECT app.payment_available_value(%s)", str(payment_id))[0])


def test_money_above_everything_owed_becomes_the_payers_credit_in_the_same_step(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    ticks = (
        invoice(case["invoice"], RENT),
        charge(case["charge"], CHARGE),
        invoice(case["later"], RENT),
    )
    command = ReceivePaymentCommand(usd(case, 2 * RENT + CHARGE + 2_000), "OLDEST_FIRST", ticks)
    result = receive(case, command)

    payment = result["payment"]["id"]
    assert result["left_usd_cents"] == 0
    assert result["credit_usd_cents"] == 2_000
    assert result["customer_credit"]["id"]
    assert credits(url, payment) == [(case["customer"], 2_000, KEPT, REASON)]
    assert left(url, payment) == 0
    assert status(url, case["invoice"]) == status(url, case["later"]) == "PAID"
    # The same press again saves nothing new and answers the same.
    assert receive(case, command) == result
    assert len(credits(url, payment)) == 1


def test_all_the_money_of_a_customer_who_owes_nothing_becomes_credit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    payer = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Customer with nothing unpaid',%s,%s)",
            (payer, case["human"], case["human"]),
        )
    result = receive(
        case,
        ReceivePaymentCommand(usd(case, 19_440, payer=payer), "OLDEST_FIRST", ()),
        who=actor(case["human"], case["prop"], "payments.record"),
    )
    assert result["allocations"] == []
    assert (result["left_usd_cents"], result["credit_usd_cents"]) == (0, 19_440)
    assert credits(url, result["payment"]["id"]) == [(payer, 19_440, KEPT, REASON)]


def test_riel_money_above_what_is_owed_becomes_usd_credit_at_the_payments_rate(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    base = usd(case, RENT)
    # $1,690.00 in riel at 4,062 riel to the dollar: $1,680.00 owed and $10.00 Credit.
    paid = receive(
        case,
        ReceivePaymentCommand(
            ConfirmKhrPaymentCommand(
                uuid4(),
                case["customer"],
                base.payment_method_id,
                (2 * RENT + CHARGE + 1_000) * 4062 // 100,
                2 * RENT + CHARGE + 1_000,
                base.received_at,
                "ABA transfer 4474",
            ),
            "OLDEST_FIRST",
            (
                invoice(case["invoice"], RENT),
                charge(case["charge"], CHARGE),
                invoice(case["later"], RENT),
            ),
        ),
        provider=provider(base.received_at),
    )
    assert paid["payment"]["received_currency"] == "KHR"
    assert (paid["left_usd_cents"], paid["credit_usd_cents"]) == (0, 1_000)
    assert credits(url, paid["payment"]["id"]) == [(case["customer"], 1_000, KEPT, REASON)]


def test_no_credit_is_made_when_the_money_is_all_used(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    result = receive(
        case,
        ReceivePaymentCommand(
            usd(case, RENT + CHARGE),
            "OLDEST_FIRST",
            (invoice(case["invoice"], RENT), charge(case["charge"], CHARGE)),
        ),
    )
    assert (result["left_usd_cents"], result["credit_usd_cents"]) == (0, 0)
    assert result["customer_credit"] is None
    assert credits(url, result["payment"]["id"]) == []


def test_when_nothing_owed_cannot_be_checked_now_the_money_waits_as_before(
    migrated_database_url: str,
) -> None:
    """Another person is changing Invoices at this moment: the payment is still saved, and the
    extra money waits on the Receipt for staff to keep it as Credit or refund it, as before."""
    url = migrated_database_url
    case = two_months(url)
    before = counts(case)
    held = threading.Event()
    done = threading.Event()

    def hold() -> None:
        with psycopg.connect(url) as connection:
            connection.execute("LOCK TABLE app.invoice_void_events IN ROW EXCLUSIVE MODE")
            held.set()
            done.wait(30)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert held.wait(10)
        result = receive(
            case,
            ReceivePaymentCommand(
                usd(case, 2 * RENT + CHARGE + 500),
                "OLDEST_FIRST",
                (
                    invoice(case["invoice"], RENT),
                    charge(case["charge"], CHARGE),
                    invoice(case["later"], RENT),
                ),
            ),
        )
    finally:
        done.set()
        holder.join()
    assert (result["left_usd_cents"], result["credit_usd_cents"]) == (500, 0)
    assert result["customer_credit"] is None
    assert credits(url, result["payment"]["id"]) == []
    assert counts(case)[0] == before[0] + 1


def test_the_migration_is_the_head(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert head == ("20270801_398",)
