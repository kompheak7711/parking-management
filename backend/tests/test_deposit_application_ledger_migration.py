"""V1-056 sub-slice 8a-2: Deposit applications in the Customer Ledger and the Deposit history."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.customer_ledger import LedgerFilter
from property_rental.customer_ledger_query import LEDGER_CAPABILITY, LedgerReadRequest
from property_rental.customer_ledger_read import CustomerLedgerReadService
from property_rental.deposit_api import PostgresDepositResourceFlow
from test_credit_migration import actor
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_migration import (
    REASON,
    another_signer_invoice,
    apply,
    charge_remaining,
    held,
    one,
    outstanding,
    overdue_lease_with_pet_damage,
    start,
)
from test_invoice_migration import runtime_database_url
from test_move_in_migration import migrated_database_url as migrated_database_url

HISTORY = "app.deposit_application_history(uuid,uuid)"
WAIT_GUARD = "app.refuse_confirmation_during_receipt_reversal_draft()"


def applied(url: str) -> dict[str, Any]:
    """The Pet Deposit pays the pet damage line first, then part of the Late-payment Charge."""
    f: dict[str, Any] = overdue_lease_with_pet_damage(url)
    prop, human = f["prop"], f["human"]
    f["settlement"] = start(prop, human, f["lease"])
    f["damage_due"] = outstanding(url, f["pet_line"])
    f["remainder"] = min(charge_remaining(url, f["charge"]), 1_000)
    f["first"] = UUID(
        str(
            apply(
                url,
                prop,
                human,
                f["settlement"],
                f["pet"],
                "PET_RELATED_FIRST",
                "INVOICE_LINE",
                f["pet_line"],
                f["damage_due"],
                1,
            )["id"]
        )
    )
    f["second"] = UUID(
        str(
            apply(
                url,
                prop,
                human,
                f["settlement"],
                f["pet"],
                "PET_REMAINDER_EXPLICIT",
                "LATE_PAYMENT_CHARGE",
                f["charge"],
                f["remainder"],
                2,
            )["id"]
        )
    )
    return f


def deposit_applied(connection: psycopg.Connection[Any], customer: UUID) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], event)
        for event in history(connection, customer)
        if event["event_kind"] == "DEPOSIT_APPLIED"
    ]


def snapshot(url: str, prop: UUID, customer: UUID, human: UUID) -> dict[str, Any]:
    """The ledger read's own reconciliation; it refuses (P4902) when effects and sources differ."""
    return cast(
        dict[str, Any],
        one(url, "SELECT app.customer_ledger_snapshot(%s,%s,%s)", prop, customer, human)[0],
    )


def test_deposit_applications_are_customer_ledger_events(migrated_database_url: str) -> None:
    url = migrated_database_url
    f = applied(url)
    prop, human, customer = f["prop"], f["human"], f["customer"]
    damage_due, remainder = f["damage_due"], f["remainder"]
    with psycopg.connect(url) as connection:
        position = assert_reconciled(connection, customer)
        events = deposit_applied(connection, customer)
    assert position.pet_deposit == 20_000 - damage_due - remainder
    # One Customer owns the Deposit and the obligations: one header with both components.
    assert [
        (
            event["event_id"],
            event["event_order"],
            event["source_table"],
            event["component_count"],
            event["recorded_amount_usd_cents"],
            event["pet_deposit_effect_usd_cents"],
            event["invoice_effect_usd_cents"],
            event["charge_effect_usd_cents"],
            event["invoice_id"],
            event["late_payment_charge_id"],
            event["deposit_id"],
        )
        for event in events
    ] == [
        (
            str(f["first"]),
            75,
            "deposit_applications",
            2,
            damage_due,
            -damage_due,
            -damage_due,
            0,
            str(f["pet_invoice"]),
            None,
            str(f["pet"]),
        ),
        (
            str(f["second"]),
            75,
            "deposit_applications",
            2,
            remainder,
            -remainder,
            0,
            -remainder,
            None,
            str(f["charge"]),
            str(f["pet"]),
        ),
    ]
    assert events[0]["source_audit"] == {
        "application_id": str(f["first"]),
        "final_settlement_id": str(f["settlement"]),
        "application_stage": "PET_RELATED_FIRST",
        "application_order": 1,
        "deposit_type": "PET",
        "deposit_customer_id": str(customer),
        "target_kind": "INVOICE_LINE",
        "target_customer_id": str(customer),
        "reason": REASON,
    }
    assert snapshot(url, prop, customer, human)["position"]["pet_deposit"] == str(
        20_000 - damage_due - remainder
    )

    # The runtime reader accepts the new kind as a history filter and shows its components.
    reader = CustomerLedgerReadService(runtime_database_url())
    staff = actor(human, prop, LEDGER_CAPABILITY)
    found = reader.get(
        customer,
        LedgerReadRequest(filters=LedgerFilter(event_kind="DEPOSIT_APPLIED")),
        actor=staff,
    )
    rows = cast(list[dict[str, Any]], cast(dict[str, Any], found["data"])["items"])
    assert [(row["event_id"], row["event_kind"]) for row in rows] == [
        (str(f["first"]), "DEPOSIT_APPLIED"),
        (str(f["second"]), "DEPOSIT_APPLIED"),
    ]
    components = reader.get(
        customer,
        LedgerReadRequest(section="components", event_kind="DEPOSIT_APPLIED", event_id=f["first"]),
        actor=staff,
    )
    parts = cast(list[dict[str, Any]], cast(dict[str, Any], components["data"])["items"])
    assert sorted(
        (part["balance_kind"], part["balance_source_id"], part["effect_usd_cents"])
        for part in parts
    ) == [
        ("INVOICE", str(f["pet_line"]), str(-damage_due)),
        ("PET_DEPOSIT", str(f["pet"]), str(-damage_due)),
    ]


def test_a_deposit_application_to_another_signer_shows_on_both_ledgers(
    migrated_database_url: str,
) -> None:
    """The Deposit owner's ledger shows the Deposit applied and names the Invoice Customer;
    the co-signer's ledger shows the Invoice paid by the Deposit application (owner answer 5)."""
    url = migrated_database_url
    f = another_signer_invoice(url)
    prop, human, tenant, co_signer = f["prop"], f["human"], f["tenant"], f["co_signer"]
    settlement = start(prop, human, f["lease"])
    application = apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "INVOICE_LINE",
        f["line"],
        2_500,
        1,
    )
    with psycopg.connect(url) as connection:
        owner_position = assert_reconciled(connection, tenant)
        signer_position = assert_reconciled(connection, co_signer)
        owner_events = deposit_applied(connection, tenant)
        signer_events = deposit_applied(connection, co_signer)
    assert (owner_position.pet_deposit, signer_position.invoice) == (17_500, 0)
    summary = [
        (
            event["event_id"],
            event["component_count"],
            event["pet_deposit_effect_usd_cents"],
            event["invoice_effect_usd_cents"],
            event["invoice_id"],
            event["deposit_id"],
            event["source_audit"]["deposit_customer_id"],
            event["source_audit"]["target_customer_id"],
        )
        for event in owner_events + signer_events
    ]
    shared = (str(f["invoice"]), str(f["pet"]), str(tenant), str(co_signer))
    assert summary == [
        (str(application["id"]), 1, -2_500, 0, *shared),
        (str(application["id"]), 1, 0, -2_500, *shared),
    ]
    # The ledger read's own reconciliation accepts both ledgers and counts every header.
    with psycopg.connect(url) as connection:
        counts = {customer: len(history(connection, customer)) for customer in (tenant, co_signer)}
    for customer, count in counts.items():
        assert snapshot(url, prop, customer, human)["event_count"] == count


def test_the_deposit_history_shows_each_application(migrated_database_url: str) -> None:
    """BR-SETTLE-009: every lower held amount has its event in the Deposit's own history."""
    url = migrated_database_url
    f = applied(url)
    page = PostgresDepositResourceFlow(runtime_database_url()).ledger(
        f["pet"], limit=50, cursor=None
    )
    applications = [event for event in page.items if event.event_kind.startswith("APPLICATION_")]
    assert [
        (
            event.event_id,
            event.event_kind,
            event.amount_usd_cents,
            event.amount_minor,
            event.currency,
            event.source_id,
            event.governing_source_kind,
            event.governing_source_id,
            event.actor_id,
            event.authorization_reference,
            event.reason,
            event.reversal_eligible,
        )
        for event in applications
    ] == [
        (
            f["second"],
            "APPLICATION_LATE_PAYMENT_CHARGE",
            f["remainder"],
            f["remainder"],
            "USD",
            f["charge"],
            "FINAL_SETTLEMENT",
            f["settlement"],
            f["human"],
            "financial.approve",
            REASON,
            False,
        ),
        (
            f["first"],
            "APPLICATION_INVOICE_LINE",
            f["damage_due"],
            f["damage_due"],
            "USD",
            f["pet_line"],
            "FINAL_SETTLEMENT",
            f["settlement"],
            f["human"],
            "financial.approve",
            REASON,
            False,
        ),
    ]
    receipts = [event for event in page.items if event.event_kind == "RECEIPT"]
    received = sum(cast(int, event.amount_usd_cents) for event in receipts)
    used = sum(cast(int, event.amount_usd_cents) for event in applications)
    assert received - used == held(url, f["pet"])
    # An applied Deposit's receipt is not offered for reversal.
    assert receipts and not any(event.reversal_eligible for event in receipts)
    # The bounded read is scoped to the Deposit's Property.
    with psycopg.connect(runtime_database_url()) as runtime:
        assert runtime.execute(
            "SELECT count(*) FROM app.deposit_application_history(%s,%s)", (f["prop"], f["pet"])
        ).fetchone() == (2,)
        assert runtime.execute(
            "SELECT count(*) FROM app.deposit_application_history(%s,%s)", (uuid4(), f["pet"])
        ).fetchone() == (0,)


def test_deposit_application_reads_are_least_privilege(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for role, expected in (
            ("prm_runtime", True),
            ("prm_financial", False),
            ("prm_bootstrap", False),
            ("prm_human_admin", False),
        ):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, HISTORY)
            ).fetchone() == (expected,), role
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, WAIT_GUARD)
            ).fetchone() == (False,), role
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.deposit_applications','SELECT')", (role,)
            ).fetchone() == (False,), role
        assert connection.execute(
            "SELECT p.prosecdef,p.proconfig FROM pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
            (HISTORY,),
        ).fetchone() == (True, ["search_path=pg_catalog"])
        assert connection.execute(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgrelid='app.financial_draft_decisions'::regclass "
            "AND tgname='financial_draft_decisions_wait_for_receipt_reversal' AND tgenabled='O'"
        ).fetchone() == (1,)


def test_deposit_application_ledger_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261023_88")
    assert revision is not None and revision.down_revision == "20261022_87"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
