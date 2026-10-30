"""Real PostgreSQL coverage of Receive payment in one step (V1-058 R5c-1; DL-077).

The payment, its Receipt and what it pays are saved in one transaction: either all of them or
none. Oldest-first ticks must be exactly what the database proposes (a late-payment charge right
after its own Invoice); named ticks pay what the payer named; money never waits while the payer
still owes something.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import database_instant, seed_method
from property_rental.identity import AuthenticatedActor
from property_rental.khr_payment_confirmation import ConfirmKhrPaymentCommand
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationKeyReused,
)
from property_rental.receive_payment import (
    PaysTarget,
    ReceivePaymentChanged,
    ReceivePaymentCommand,
    ReceivePaymentLeftWhileOwing,
    ReceivePaymentService,
    read_payable,
)
from test_credit_migration import actor
from test_final_settlement_migration import one
from test_invoice_migration import financial_database_url, runtime_database_url
from test_khr_payment_confirmation import provider
from test_late_charge_payment_proposal_migration import CHARGE, RENT, status, two_months
from test_late_payment_charge_reduction_migration import position
from test_late_payment_migration import migrated_database_url as migrated_database_url

REVISION = "20270311_230"


def cashier(case: dict[str, Any]) -> AuthenticatedActor:
    return actor(case["human"], case["prop"], "payments.record", "payments.allocate")


def usd(
    case: dict[str, Any], amount: int, *, payer: UUID | None = None
) -> ConfirmUsdPaymentCommand:
    with psycopg.connect(case["url"]) as connection:
        method = seed_method(connection, case["human"])
        at = database_instant(connection) - timedelta(seconds=1)
    return ConfirmUsdPaymentCommand(
        uuid4(), payer or case["customer"], method, amount, at, "Receipt book page 12"
    )


def invoice(target: UUID, amount: int) -> PaysTarget:
    return PaysTarget("INVOICE", target, amount)


def charge(target: UUID, amount: int) -> PaysTarget:
    return PaysTarget("LATE_PAYMENT_CHARGE", target, amount)


def receive(case: dict[str, Any], command: ReceivePaymentCommand, **kinds: Any) -> dict[str, Any]:
    service = ReceivePaymentService(financial_database_url(), kinds.pop("provider", provider()))
    return cast(
        dict[str, Any],
        service.receive(case["prop"], command, actor=kinds.pop("who", cashier(case))),
    )


def counts(case: dict[str, Any]) -> tuple[int, int, int, int]:
    """Payments, Receipts, allocations and Receive payment commands of the Property."""
    row = one(
        case["url"],
        "SELECT (SELECT count(*) FROM app.payments WHERE property_id=%s),"
        "(SELECT count(*) FROM app.receipts receipt JOIN app.payments payment "
        "ON payment.id=receipt.payment_id WHERE payment.property_id=%s),"
        "(SELECT count(*) FROM app.payment_allocations allocation JOIN app.payments payment "
        "ON payment.id=allocation.payment_id WHERE payment.property_id=%s),"
        "(SELECT count(*) FROM app.receive_payment_commands WHERE property_id=%s)",
        case["prop"],
        case["prop"],
        case["prop"],
        case["prop"],
    )
    return cast(tuple[int, int, int, int], tuple(int(cast(int, value)) for value in row))


def number(url: str, target: UUID) -> str:
    return str(one(url, "SELECT invoice_number FROM app.invoices WHERE id=%s", target)[0])


def test_oldest_first_saves_the_payment_its_receipt_and_what_it_pays_together(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    before = counts(case)
    ticks = (
        invoice(case["invoice"], RENT),
        charge(case["charge"], CHARGE),
        invoice(case["later"], RENT),
    )
    command = ReceivePaymentCommand(usd(case, 2 * RENT + CHARGE + 2_000), "OLDEST_FIRST", ticks)
    result = receive(case, command)

    assert result["pays_mode"] == "OLDEST_FIRST"
    assert result["left_usd_cents"] == 2_000
    assert result["receipt"]["receipt_number"]
    assert [
        (item["target_kind"], item["invoice_number"], item["amount_usd_cents"])
        for item in result["allocations"]
    ] == [
        ("INVOICE", number(url, case["invoice"]), RENT),
        ("LATE_PAYMENT_CHARGE", number(url, case["invoice"]), CHARGE),
        ("INVOICE", number(url, case["later"]), RENT),
    ]
    assert result["allocations"][1]["late_payment_charge_id"] == str(case["charge"])
    assert status(url, case["invoice"]) == status(url, case["later"]) == "PAID"
    assert position(url, case["charge"]) == (CHARGE, 0)
    assert counts(case) == (before[0] + 1, before[1] + 1, before[2] + 3, before[3] + 1)

    # The same press again (no answer the first time) saves nothing new.
    assert receive(case, command) == result
    assert counts(case) == (before[0] + 1, before[1] + 1, before[2] + 3, before[3] + 1)
    # The same key with another request is refused.
    other = ReceivePaymentCommand(
        ConfirmUsdPaymentCommand(
            command.confirmation.idempotency_key,
            case["customer"],
            command.confirmation.payment_method_id,
            2 * RENT + CHARGE,
            command.confirmation.received_at,
            "Receipt book page 12",
        ),
        "OLDEST_FIRST",
        ticks,
    )
    with pytest.raises(PaymentConfirmationKeyReused):
        receive(case, other)


def test_ticks_that_differ_from_the_proposal_save_nothing(migrated_database_url: str) -> None:
    case = two_months(migrated_database_url)
    before = counts(case)
    # The screen showed only the Invoice, but the charge comes right after it now.
    stale = ReceivePaymentCommand(
        usd(case, RENT + CHARGE), "OLDEST_FIRST", (invoice(case["invoice"], RENT),)
    )
    with pytest.raises(ReceivePaymentChanged):
        receive(case, stale)
    # Nothing ticked while the Customer owes: also refused, nothing waits.
    with pytest.raises(ReceivePaymentChanged):
        receive(case, ReceivePaymentCommand(usd(case, 500), "OLDEST_FIRST", ()))
    assert counts(case) == before
    assert status(migrated_database_url, case["invoice"]) == "UNPAID"
    # The confirmation key was not used up: the same key with the right ticks saves.
    right = ReceivePaymentCommand(
        stale.confirmation,
        "OLDEST_FIRST",
        (invoice(case["invoice"], RENT), charge(case["charge"], CHARGE)),
    )
    assert receive(case, right)["left_usd_cents"] == 0


def test_money_from_a_customer_who_owes_nothing_waits_on_the_receipt(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    payer = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Customer with nothing unpaid',%s,%s)",
            (payer, case["human"], case["human"]),
        )
    # Recording alone is enough when nothing is ticked.
    result = receive(
        case,
        ReceivePaymentCommand(usd(case, 19_440, payer=payer), "OLDEST_FIRST", ()),
        who=actor(case["human"], case["prop"], "payments.record"),
    )
    assert result["allocations"] == [] and result["left_usd_cents"] == 19_440
    assert result["payment"]["payer_customer_id"] == str(payer)


def test_named_ticks_pay_what_the_payer_named(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    result = receive(
        case,
        ReceivePaymentCommand(usd(case, RENT), "NAMED", (invoice(case["later"], RENT),)),
    )
    assert [(item["invoice_id"], item["amount_usd_cents"]) for item in result["allocations"]] == [
        (str(case["later"]), RENT)
    ]
    assert result["left_usd_cents"] == 0
    assert status(url, case["later"]) == "PAID" and status(url, case["invoice"]) == "UNPAID"
    row = one(
        url,
        "SELECT between_invoice_basis,customer_designation_reference "
        "FROM app.payment_allocations WHERE id=%s",
        result["allocations"][0]["allocation_id"],
    )
    assert row == ("CUSTOMER_DESIGNATED", "Named by the payer at Receive payment")

    # A named charge is paid directly.
    paid = receive(
        case,
        ReceivePaymentCommand(usd(case, 3_000), "NAMED", (charge(case["charge"], 3_000),)),
    )
    assert paid["allocations"][0]["target_kind"] == "LATE_PAYMENT_CHARGE"
    assert position(url, case["charge"]) == (CHARGE, CHARGE - 3_000)


def test_named_ticks_never_leave_money_waiting_while_something_is_owed(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    before = counts(case)
    with pytest.raises(ReceivePaymentLeftWhileOwing):
        receive(
            case,
            ReceivePaymentCommand(
                usd(case, RENT + 4_700), "NAMED", (invoice(case["later"], RENT),)
            ),
        )
    # More than the named Invoice owes is refused as a change too.
    with pytest.raises(ReceivePaymentChanged):
        receive(
            case,
            ReceivePaymentCommand(
                usd(case, RENT + 1), "NAMED", (invoice(case["later"], RENT + 1),)
            ),
        )
    assert counts(case) == before


def test_khr_money_pays_oldest_first_in_the_same_step(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    base = usd(case, RENT)
    khr = ConfirmKhrPaymentCommand(
        base.idempotency_key,
        case["customer"],
        base.payment_method_id,
        3_266_400,
        RENT,
        base.received_at,
        "ABA transfer 4471",
    )
    result = receive(
        case,
        ReceivePaymentCommand(khr, "OLDEST_FIRST", (invoice(case["invoice"], RENT),)),
        provider=provider(base.received_at),
    )
    assert result["payment"]["received_currency"] == "KHR"
    assert result["exchange_rate_record"]["system_rate_khr_per_usd"] == 4083
    assert status(url, case["invoice"]) == "PAID" and result["left_usd_cents"] == 0


def test_named_ticks_need_allocate_and_only_the_financial_role_may_call_the_command(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    with pytest.raises(PaymentConfirmationAuthorizationError):
        receive(
            case,
            ReceivePaymentCommand(usd(case, RENT), "NAMED", (invoice(case["invoice"], RENT),)),
            who=actor(case["human"], case["prop"], "payments.record"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        grants = connection.execute(
            "SELECT role,has_function_privilege(role,"
            "'app.receive_payment(uuid,uuid,uuid,text,jsonb,jsonb,jsonb)','EXECUTE'),"
            "has_function_privilege(role,'app.receive_payment_replay(uuid,uuid,uuid,text)',"
            "'EXECUTE'),has_function_privilege(role,'app.receive_payment_payable(uuid,uuid)',"
            "'EXECUTE'),has_table_privilege(role,'app.receive_payment_commands','SELECT') "
            "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap']) role ORDER BY role"
        ).fetchall()
        assert grants == [
            ("prm_bootstrap", False, False, False, False),
            ("prm_financial", True, True, True, False),
            ("prm_runtime", False, False, True, False),
        ]
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert head == ("20270407_257",)


def test_receive_payment_commands_are_append_only(migrated_database_url: str) -> None:
    case = two_months(migrated_database_url)
    receive(
        case,
        ReceivePaymentCommand(
            usd(case, RENT + CHARGE),
            "OLDEST_FIRST",
            (invoice(case["invoice"], RENT), charge(case["charge"], CHARGE)),
        ),
    )
    for statement in (
        "UPDATE app.receive_payment_commands SET recorded_at=recorded_at WHERE property_id=%s",
        "DELETE FROM app.receive_payment_commands WHERE property_id=%s",
        "TRUNCATE app.receive_payment_commands",
    ):
        with (
            psycopg.connect(migrated_database_url) as connection,
            pytest.raises(psycopg.Error) as refused,
        ):
            connection.execute(statement, (case["prop"],) if "%s" in statement else None)
        assert refused.value.sqlstate == "55000"


def test_the_payable_list_is_in_the_order_oldest_first_ticks_pay_it(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    found = read_payable(
        runtime_database_url(), case["prop"], case["customer"], actor=cashier(case)
    )
    assert [
        (item["kind"], item["id"], item["invoice_number"], item["owed_usd_cents"])
        for item in cast(list[dict[str, object]], found["items"])
    ] == [
        ("INVOICE", str(case["invoice"]), number(url, case["invoice"]), RENT),
        ("LATE_PAYMENT_CHARGE", str(case["charge"]), number(url, case["invoice"]), CHARGE),
        ("INVOICE", str(case["later"]), number(url, case["later"]), RENT),
    ]
    assert cast(list[dict[str, object]], found["items"])[1]["invoice_id"] == str(case["invoice"])
    # Part paid: the list shows what is still owed, and a paid Invoice leaves it.
    receive(
        case,
        ReceivePaymentCommand(
            usd(case, RENT + 3_000),
            "OLDEST_FIRST",
            (invoice(case["invoice"], RENT), charge(case["charge"], 3_000)),
        ),
    )
    after = read_payable(
        runtime_database_url(), case["prop"], case["customer"], actor=cashier(case)
    )
    assert [
        (item["id"], item["owed_usd_cents"])
        for item in cast(list[dict[str, object]], after["items"])
    ] == [
        (str(case["charge"]), CHARGE - 3_000),
        (str(case["later"]), RENT),
    ]
    with pytest.raises(PaymentConfirmationAuthorizationError):
        read_payable(
            runtime_database_url(),
            case["prop"],
            case["customer"],
            actor=actor(case["human"], case["prop"], "invoices.read"),
        )


def test_a_payment_that_names_an_invoice_is_refused_by_the_database_too(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    before = counts(case)
    request = usd(case, RENT).intent()
    for named in (
        {"identified_invoice_id": str(case["invoice"])},
        {"identified_late_payment_charge_id": str(case["charge"])},
        {"payment_scope_kind": "THIRD_PARTY_IDENTIFIED", "lease_id": str(case["lease"])},
    ):
        with (
            psycopg.connect(financial_database_url()) as connection,
            pytest.raises(psycopg.Error) as refused,
        ):
            connection.execute(
                "SELECT app.receive_payment(%s,%s,%s,%s,%s,NULL,%s)",
                (
                    case["prop"],
                    case["human"],
                    uuid4(),
                    "0" * 64,
                    Jsonb({**request, **named}),
                    Jsonb({"mode": "OLDEST_FIRST", "targets": []}),
                ),
            )
        assert refused.value.sqlstate == "P5302"
    assert counts(case) == before


def test_a_khr_retry_keeps_the_first_rate_and_asks_for_no_new_one(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    base = usd(case, RENT)
    khr = ConfirmKhrPaymentCommand(
        base.idempotency_key,
        case["customer"],
        base.payment_method_id,
        3_266_400,
        RENT,
        base.received_at,
        "ABA transfer 4472",
    )
    command = ReceivePaymentCommand(khr, "OLDEST_FIRST", (invoice(case["invoice"], RENT),))
    first_rate = provider(base.received_at)
    first = receive(case, command, provider=first_rate)
    later_rate = provider(base.received_at)
    later_rate.quote = replace(later_rate.quote, reference_rate_khr_per_usd=Decimal("4100"))
    assert receive(case, command, provider=later_rate) == first
    assert first_rate.calls == 1 and later_rate.calls == 0


def test_two_presses_at_once_save_one_payment(migrated_database_url: str) -> None:
    case = two_months(migrated_database_url)
    before = counts(case)
    command = ReceivePaymentCommand(
        usd(case, RENT + CHARGE),
        "OLDEST_FIRST",
        (invoice(case["invoice"], RENT), charge(case["charge"], CHARGE)),
    )
    start = Barrier(2)

    def press() -> dict[str, Any]:
        start.wait()
        return receive(case, command)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: press(), range(2)))
    assert results[0] == results[1]
    assert counts(case) == (before[0] + 1, before[1] + 1, before[2] + 2, before[3] + 1)
