"""Real PostgreSQL coverage of migration `20270215_203` (V1-056 slice 12a).

Settings writers name `settings.manage` in their audit evidence (Q-2026-10-24-186), and the
hand-back assessment says KEEP for an Invoice a credit Adjustment took to zero (slice 11a
review round 1, S2).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from property_rental.invoice import AdjustInvoiceCommand, AdjustmentType
from test_configuration_migration import actor_and_property
from test_hand_back_rent_migration import (
    AUGUST,
    hand_back,
    hand_back_database,  # noqa: F401
    invoices,
    lease_with_invoices,
    lines,
    raw_resolve,
    resolution_count,
    staff,
    status,
    version,
)
from test_invoice_migration import migrated_database_url as migrated_database_url


def test_a_utility_rate_change_names_settings_manage(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        setup.commit()
    rate_id = uuid4()
    # One transaction, rolled back, so the shared rate list does not change for other tests.
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "SELECT * FROM app.execute_utility_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                uuid4(),
                "e" * 64,
                rate_id,
                "WATER",
                "M3",
                Decimal("0.50000000"),
                "2098-10-01",
                "2098-09-01T09:00:00+07:00",
                "Notice WATER-2098-09",
                "Approved rate",
                actor_id,
            ),
        )
        assert connection.execute(
            "SELECT action,authorization_reference FROM app.audit_events WHERE id=%s", (rate_id,)
        ).fetchone() == ("utility_rate.created", "settings.manage")
        connection.rollback()


def test_an_invoice_credit_adjusted_to_zero_is_kept_at_hand_back(
    hand_back_database: str,  # noqa: F811
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    who = staff(scenario.human, scenario.prop)
    for line, _, amount in lines(url, august):
        invoices().adjust(
            scenario.prop,
            august,
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.CREDIT,
                amount,
                "slice-12a-credit",
                "Credit the whole month",
                version(url, august),
            ),
            actor=who,
        )
    hand_back(url, scenario, date(2026, 8, 4))
    before = (version(url, august), status(url, august))
    assessment = invoices().hand_back_rent_assessment(scenario.prop, august, actor=who)
    assert (
        assessment["action"],
        assessment["applied_usd_cents"],
        assessment["outstanding_usd_cents"],
    ) == ("KEEP", 0, 0)
    for action in ("VOID", "CREDIT_ADJUSTMENT"):
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="kept as issued"):
            raw_resolve(scenario, august, action, version(url, august), 1)
    assert resolution_count(url, august) == 0
    assert (version(url, august), status(url, august)) == before
