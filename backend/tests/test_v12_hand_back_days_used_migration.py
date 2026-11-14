"""DL-229 (D1, owner 12 Nov 2026), migration 20270725_378: a hand-back before the 5th pays only
the days used.

Before this migration the tenant who had paid the month lost all of it, and the tenant who had
not paid owed nothing (the Invoice was made Void). Now both pay the same: the days from the 1st
to the hand-back day, by the real days of the month (BR-RENT-006). The rest of each line of the
monthly Rent Invoice is removed by a credit Adjustment; what the Customer paid for unused days
becomes Customer Credit. The next month's Invoice, already made when the hand-back is on or
after the 25th, has no day used: it is made Void when nothing is paid, and paid money comes back
as Customer Credit.

The example of the tests: Rent 800.00 USD, Trash Collection 10.00 USD, August has 31 days.
A hand-back on 3 August keeps 800.00 x 3 / 31 = 77.42 and 10.00 x 3 / 31 = 0.97.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.invoice import (
    InvoiceAuthorizationError,
    InvoiceConflictError,
    ResolveHandBackRentCommand,
)
from test_hand_back_rent_migration import (
    AUGUST,
    SEPTEMBER,
    Scenario,
    hand_back,
    invoices,
    lease_with_invoices,
    lines,
    pay,
    resolution_count,
    resolve_as_shown,
    scalar,
    staff,
    status,
    version,
)
from test_hand_back_rent_migration import hand_back_database as hand_back_database
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url

REVISION = "20270725_378"
RESOLVE = "app.resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,bigint,text)"
OLD_RESOLVE = "resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,text)"


def assess(scenario: Scenario, invoice: UUID) -> dict[str, Any]:
    return invoices().hand_back_rent_assessment(
        scenario.prop, invoice, actor=staff(scenario.human, scenario.prop)
    )


def line_state(url: str, invoice: UUID) -> list[tuple[int, int, int]]:
    """Each line in order: what is owed for it now, what is applied to it, what is unpaid."""
    with psycopg.connect(url) as connection:
        return [
            (int(owed), int(applied), int(unpaid))
            for owed, applied, unpaid in connection.execute(
                "SELECT app.invoice_adjusted_line_obligation(id),"
                "app.invoice_line_application_value_at(id,'infinity'),"
                "app.invoice_line_outstanding(id) FROM app.invoice_lines WHERE invoice_id=%s "
                "ORDER BY line_sequence,id",
                (invoice,),
            )
        ]


def credit_from_adjustments(url: str, scenario: Scenario) -> int:
    """Customer Credit the Customer got back from credit Adjustments."""
    return int(
        scalar(
            url,
            "SELECT COALESCE(sum(recognized_usd_cents),0) FROM app.customer_credits "
            "WHERE customer_id=%s "
            "AND customer_authorization_reference LIKE 'invoice-adjustment:%%'",
            (scenario.customer,),
        )
    )


def test_migration_378_follows_393_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270724_393"
    with pytest.raises(RuntimeError, match="forward-only"):
        cast(Any, revision.module).downgrade()


def test_the_tenant_who_did_not_pay_owes_the_days_used(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,), trash=True)
    august = scenario.invoices[AUGUST]
    move_out = hand_back(url, scenario, date(2026, 8, 3)).event_id
    shown = assess(scenario, august)
    assert {
        key: shown[key]
        for key in (
            "coverage",
            "action",
            "days_used",
            "days_in_month",
            "applied_usd_cents",
            "outstanding_usd_cents",
            "kept_usd_cents",
            "credit_usd_cents",
            "released_usd_cents",
        )
    } == {
        "coverage": "HAND_BACK_MONTH",
        "action": "CREDIT_ADJUSTMENT",
        "days_used": 3,
        "days_in_month": 31,
        "applied_usd_cents": 0,
        "outstanding_usd_cents": 81_000,
        "kept_usd_cents": 7_839,
        "credit_usd_cents": 73_161,
        "released_usd_cents": 0,
    }
    assert [
        (line["category"], line["kept_usd_cents"], line["credit_usd_cents"])
        for line in cast(list[dict[str, Any]], shown["lines"])
    ] == [("RENT", 7_742, 72_258), ("SERVICE_CHARGES", 97, 903)]
    request = ResolveHandBackRentCommand(
        uuid4(),
        "CREDIT_ADJUSTMENT",
        81_000,
        "Handed back on 3 August",
        version(url, august),
        73_161,
    )
    # Lowering an Invoice is an Adjustment: the right to make an Invoice Void is not enough.
    with pytest.raises(InvoiceAuthorizationError):
        invoices().resolve_hand_back_rent(
            scenario.prop,
            august,
            request,
            actor=staff(scenario.human, scenario.prop, "invoices.read", "invoices.void"),
        )
    who = staff(scenario.human, scenario.prop)
    for stale in (
        replace(request, expected_action="VOID"),
        replace(request, expected_credit_usd_cents=81_000),
        replace(request, expected_outstanding_usd_cents=80_000),
    ):
        with pytest.raises(InvoiceConflictError):
            invoices().resolve_hand_back_rent(scenario.prop, august, stale, actor=who)
    resolved = invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who)
    assert resolved["action"] == "CREDIT_ADJUSTMENT"
    assert len(cast(list[str], resolved["adjustment_ids"])) == 2
    assert invoices().resolve_hand_back_rent(scenario.prop, august, request, actor=who) == resolved
    assert status(url, august) == "UNPAID"
    assert line_state(url, august) == [(7_742, 0, 7_742), (97, 0, 97)]
    assert credit_from_adjustments(url, scenario) == 0
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT physical_move_out_event_id,hand_back_date,coverage,action,"
            "authorization_reference,days_used,days_in_month,kept_usd_cents,credit_usd_cents,"
            "released_usd_cents,expected_outstanding_usd_cents,invoice_void_event_id "
            "FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
            (august,),
        ).fetchall() == [
            (
                move_out,
                date(2026, 8, 3),
                "HAND_BACK_MONTH",
                "CREDIT_ADJUSTMENT",
                "invoices.adjust",
                3,
                31,
                7_839,
                73_161,
                0,
                81_000,
                None,
            )
        ]
        assert connection.execute(
            "SELECT authorization_evidence->>'rule',authorization_evidence->>'decision' "
            "FROM app.audit_events WHERE action='invoice.hand_back_rent.resolved' "
            "AND entity_id=%s",
            (august,),
        ).fetchall() == [("BR-RENT-012", "DL-229")]
    # The Invoice is not Void: the month has its Invoice, for the days used.
    assert lines(url, august) == [
        (line, category, amount)
        for (line, category, amount) in lines(url, august)
        if amount in (80_000, 1_000)
    ]


def test_the_tenant_who_paid_gets_the_unused_days_back_as_customer_credit(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,), trash=True)
    august = scenario.invoices[AUGUST]
    for line, _, amount in lines(url, august):
        pay(url, scenario, august, line, amount)
    assert status(url, august) == "PAID"
    hand_back(url, scenario, date(2026, 8, 3))
    shown = assess(scenario, august)
    assert (
        shown["action"],
        shown["applied_usd_cents"],
        shown["outstanding_usd_cents"],
        shown["kept_usd_cents"],
        shown["credit_usd_cents"],
        shown["released_usd_cents"],
    ) == ("CREDIT_ADJUSTMENT", 81_000, 0, 7_839, 73_161, 73_161)
    resolve_as_shown(url, scenario, august)
    assert status(url, august) == "PAID"
    assert line_state(url, august) == [(7_742, 7_742, 0), (97, 97, 0)]
    # The Payments are not changed; the money for the unused days is the Customer's Credit.
    assert credit_from_adjustments(url, scenario) == 73_161
    assert (
        scalar(
            url,
            "SELECT released_usd_cents FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
            (august,),
        )
        == 73_161
    )


def test_a_part_payment_above_the_days_used_gives_the_rest_back(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,), trash=True)
    august = scenario.invoices[AUGUST]
    (rent, _, _), _ = lines(url, august)
    pay(url, scenario, august, rent, 20_000)
    hand_back(url, scenario, date(2026, 8, 4))
    shown = assess(scenario, august)
    # 4 of 31 days: Rent 103.23, Trash Collection 1.29.
    assert (
        shown["action"],
        shown["days_used"],
        shown["kept_usd_cents"],
        shown["credit_usd_cents"],
        shown["released_usd_cents"],
    ) == ("CREDIT_ADJUSTMENT", 4, 10_452, 70_548, 9_677)
    resolve_as_shown(url, scenario, august)
    assert line_state(url, august) == [(10_323, 10_323, 0), (129, 0, 129)]
    assert status(url, august) == "PARTIALLY_PAID"
    assert credit_from_adjustments(url, scenario) == 9_677


def test_a_part_payment_below_the_days_used_leaves_the_rest_owed(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    ((rent, _, _),) = lines(url, august)
    pay(url, scenario, august, rent, 5_000)
    hand_back(url, scenario, date(2026, 8, 4))
    shown = assess(scenario, august)
    assert (shown["kept_usd_cents"], shown["credit_usd_cents"], shown["released_usd_cents"]) == (
        10_323,
        69_677,
        0,
    )
    resolve_as_shown(url, scenario, august)
    assert line_state(url, august) == [(10_323, 5_000, 5_323)]
    assert status(url, august) == "PARTIALLY_PAID"
    assert credit_from_adjustments(url, scenario) == 0


@pytest.mark.parametrize(("day", "kept"), [(1, 2_581), (2, 5_161), (3, 7_742), (4, 10_323)])
def test_the_hand_back_day_is_a_day_used(hand_back_database: str, day: int, kept: int) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    hand_back(url, scenario, date(2026, 8, day))
    shown = assess(scenario, scenario.invoices[AUGUST])
    assert (shown["days_used"], shown["kept_usd_cents"], shown["credit_usd_cents"]) == (
        day,
        kept,
        80_000 - kept,
    )


def test_on_the_5th_and_later_the_month_is_charged_in_full(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    hand_back(url, scenario, date(2026, 8, 5))
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="not covered"):
        with psycopg.connect(runtime_database_url()) as connection:
            connection.execute(
                "SELECT app.hand_back_rent_invoice_assessment(%s,%s,%s)",
                (scenario.prop, scenario.human, august),
            )
    assert line_state(url, august) == [(80_000, 0, 80_000)]
    assert resolution_count(url, august) == 0


def test_the_next_month_has_no_day_used_void_when_unpaid_and_all_back_when_paid(
    hand_back_database: str,
) -> None:
    url = hand_back_database
    paid = lease_with_invoices(url, (AUGUST, SEPTEMBER), trash=True)
    unpaid = lease_with_invoices(url, (AUGUST, SEPTEMBER), trash=True)
    september = paid.invoices[SEPTEMBER]
    for line, _, amount in lines(url, september):
        pay(url, paid, september, line, amount)
    hand_back(url, paid, date(2026, 8, 27))
    hand_back(url, unpaid, date(2026, 8, 25))

    shown = assess(paid, september)
    assert (
        shown["coverage"],
        shown["action"],
        shown["days_used"],
        shown["days_in_month"],
        shown["kept_usd_cents"],
        shown["credit_usd_cents"],
        shown["released_usd_cents"],
    ) == ("NEXT_MONTH", "CREDIT_ADJUSTMENT", 0, 30, 0, 81_000, 81_000)
    resolve_as_shown(url, paid, september)
    assert line_state(url, september) == [(0, 0, 0), (0, 0, 0)]
    assert credit_from_adjustments(url, paid) == 81_000
    assert status(url, september) != "VOID"

    next_month = unpaid.invoices[SEPTEMBER]
    shown = assess(unpaid, next_month)
    assert (shown["coverage"], shown["action"], shown["credit_usd_cents"]) == (
        "NEXT_MONTH",
        "VOID",
        81_000,
    )
    resolved = resolve_as_shown(url, unpaid, next_month)
    assert resolved["action"] == "VOID" and resolved["adjustment_ids"] == []
    assert status(url, next_month) == "VOID"
    assert credit_from_adjustments(url, unpaid) == 0
    # The hand-back month itself, handed back on the 25th or later, is charged in full.
    for scenario in (paid, unpaid):
        august = scenario.invoices[AUGUST]
        assert line_state(url, august) == [(80_000, 0, 80_000), (1_000, 0, 1_000)]
        assert resolution_count(url, august) == 0


def test_an_invoice_already_at_the_days_used_is_kept(hand_back_database: str) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    hand_back(url, scenario, date(2026, 8, 3))
    resolve_as_shown(url, scenario, august)
    # One hand-back resolution for an Invoice, as before.
    with pytest.raises(InvoiceConflictError):
        invoices().resolve_hand_back_rent(
            scenario.prop,
            august,
            ResolveHandBackRentCommand(
                uuid4(), "CREDIT_ADJUSTMENT", 7_742, "Again", version(url, august), 1
            ),
            actor=staff(scenario.human, scenario.prop),
        )
    shown = assess(scenario, august)
    assert (shown["action"], shown["kept_usd_cents"], shown["credit_usd_cents"]) == (
        "KEEP",
        7_742,
        0,
    )
    assert resolution_count(url, august) == 1


def test_the_new_command_is_least_privilege_and_the_old_one_is_gone(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc WHERE pronamespace='app'::regnamespace "
            "AND proname='resolve_hand_back_rent_invoice'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT to_regprocedure(%s)", (f"app.{OLD_RESOLVE}",)
        ).fetchone() == (None,)
    for url, allowed in ((runtime_database_url(), False), (financial_database_url(), True)):
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (RESOLVE,)
            ).fetchone() == (allowed,), url
            assert connection.execute(
                "SELECT has_table_privilege(current_user,'app.hand_back_rent_resolutions','SELECT')"
            ).fetchone() == (False,), url
