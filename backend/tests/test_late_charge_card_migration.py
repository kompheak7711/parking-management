"""Real PostgreSQL coverage of the late-payment card read (V1-058 R5d).

The Invoice page shows, for an Invoice with a late-payment charge, what was unpaid at the charge
moment, the rate, the amount the app added, each reduction or waiver with its reason, what paid
the charge (with the Receipt number) and what is still owed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import ReductionReason
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadService,
    late_charge_card,
)
from property_rental.receive_payment import ReceivePaymentCommand
from test_final_settlement_migration import one
from test_invoice_migration import runtime_database_url
from test_late_charge_payment_proposal_migration import two_months
from test_late_payment_charge_reduction_migration import WHAT, charged, reduce
from test_late_payment_charge_reduction_migration import no_pass_yet as no_pass_yet
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_receive_payment_migration import charge, invoice, receive, usd

FUNCTION = "app.invoice_late_charge_card(uuid,uuid,uuid)"


def reader_actor(case: dict[str, Any], capability: str = "invoices.read") -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(case["human"]),
        capability_grants=frozenset({CapabilityGrant(capability, frozenset({str(case["prop"])}))}),
    )


def card(case: dict[str, Any], invoice: UUID | None = None) -> dict[str, Any] | None:
    return cast(
        "dict[str, Any] | None",
        late_charge_card(
            PaymentReadService(runtime_database_url()),
            case["prop"],
            invoice or case["invoice"],
            actor=reader_actor(case),
        ),
    )


def test_the_card_shows_the_charge_its_reduction_and_what_paid_it(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 18)
    first = card(case)
    assert first is not None
    assert first["charge_id"] == str(case["charge"])
    assert first["invoice_id"] == str(case["invoice"])
    assert first["customer_id"] == str(case["customer"])
    assert first["by_app"] is True and first["added_by"] is None
    assert first["rate_basis_points"] == 1000
    assert first["decision_outcome"] == "CONFIRMED_DEFAULT"
    assert first["calculated_default_usd_cents"] == 8_000
    charged_at = datetime.fromisoformat(first["charged_at"])
    assert charged_at <= datetime.fromisoformat(first["payable_at"])
    assert first["unpaid_at_charge_usd_cents"] == 80_000
    assert first["original_usd_cents"] == 8_000
    assert first["now_usd_cents"] == 8_000 and first["still_owed_usd_cents"] == 8_000
    assert first["paid_usd_cents"] == 0
    assert first["changes"] == [] and first["paid_by"] == []

    ticks = (invoice(case["invoice"], 80_000), charge(case["charge"], 3_000))
    paid_now = receive(case, ReceivePaymentCommand(usd(case, 83_000), "OLDEST_FIRST", ticks))
    payment = paid_now["payment"]["id"]
    reduce(case, 5_000, ReductionReason.WRONG_INVOICE)

    after = card(case)
    assert after is not None
    assert after["original_usd_cents"] == 8_000
    assert after["now_usd_cents"] == 5_000
    assert after["paid_usd_cents"] == 3_000 and after["still_owed_usd_cents"] == 2_000
    [change] = after["changes"]
    assert change["kind"] == "REDUCTION"
    assert change["previous_usd_cents"] == 8_000 and change["resulting_usd_cents"] == 5_000
    assert change["reason_code"] == "WRONG_INVOICE" and change["what_happened"] == WHAT
    assert change["by"] and change["at"]
    [paid] = after["paid_by"]
    assert paid["kind"] == "PAYMENT" and paid["payment_id"] == payment
    assert paid["amount_usd_cents"] == 3_000
    assert paid["receipt_number"] == paid_now["receipt"]["receipt_number"]


def test_no_charge_another_property_and_the_read_rights(migrated_database_url: str) -> None:
    url = migrated_database_url
    # The next month's Rent Invoice of the Lease has no charge.
    case = two_months(url)
    assert card(case, case["later"]) is None
    assert card(case, uuid4()) is None

    with pytest.raises(PaymentReadAuthorizationError):
        late_charge_card(
            PaymentReadService(runtime_database_url()),
            case["prop"],
            case["invoice"],
            actor=reader_actor(case, "payments.read"),
        )
    with psycopg.connect(runtime_database_url()) as connection, pytest.raises(psycopg.Error):
        connection.execute(
            f"SELECT {FUNCTION.split('(')[0]}(%s,%s,%s)",
            (case["prop"], uuid4(), case["invoice"]),
        )
    privileges = one(
        url,
        "SELECT has_function_privilege('prm_runtime',%s,'EXECUTE'),"
        "has_function_privilege('prm_financial',%s,'EXECUTE'),"
        "has_function_privilege('public',%s,'EXECUTE')",
        FUNCTION,
        FUNCTION,
        FUNCTION,
    )
    assert privileges == (True, True, False)
