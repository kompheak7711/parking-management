"""Migration 20270331_250 (V1-060 B7 second review, DL-109): Sign Lease refuses a draft whose
Reservation ended.

A Lease from a Reservation takes that Reservation's Security Deposit (DL-100); a Reservation that
ended keeps its Security Deposit for its own outcome (DL-009). So a draft whose Reservation was
cancelled, expired (DL-004 cancels it) or replaced by a new Reservation of the Unit is refused, and
nothing is saved. A Lease that is not a renewal ends with exactly one Security Deposit, received in
full.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_method
from property_rental.api_refusals import RefusedRequest
from property_rental.billing import month_end
from property_rental.reservation import CancellationResponsibility
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_lifecycle_migration import draft_command
from test_lease_migration import create_draft
from test_lease_security_deposit_migration import cancel, expire
from test_lease_signing_reservation_migration import business_date, leases, reserved_unit
from test_reservation_lifecycle_migration import expired_reservation
from test_reservation_migration import create_reservation
from test_sign_lease_in_one_step_migration import (
    _command,
    _counts,
    _due,
    _one,
    _plan,
    _sign,
    _status,
    _walk_in,
)


def _draft_of(
    url: str,
    found: tuple[UUID, UUID, UUID, UUID, UUID, UUID],
    *,
    names_deposit: bool = True,
) -> dict[str, Any]:
    """A draft Lease for a Reservation's Unit and Customer, naming the Reservation's Security
    Deposit (or naming none, as a walk-in draft does)."""
    actor, prop, unit, customer, reservation, deposit = found
    service, who = leases(actor, prop)
    today = business_date(url, prop)
    draft = draft_command(
        unit, customer, start_date=today, end_date=month_end(today + timedelta(days=365))
    )
    if names_deposit:
        draft = replace(draft, security_deposit_id=deposit)
    service.draft_with_terms(draft, actor=who)
    with psycopg.connect(url) as connection:
        method = seed_method(connection, actor)
    return {
        "url": url,
        "actor": actor,
        "human": actor,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "lease": draft.lease_id,
        "method": method,
        "reservation": reservation,
        "deposit": deposit,
    }


def _deposit(case: dict[str, Any], deposit: object) -> tuple[Any, ...]:
    """The Security Deposit's Lease, required amount and money received."""
    return _one(
        case["url"],
        "SELECT lease_id, (s->>'required_usd_cents')::bigint, (s->>'received_usd_cents')::bigint "
        "FROM app.deposits, LATERAL (SELECT app.deposit_snapshot(id) AS s) AS d WHERE id=%s",
        deposit,
    )


def _reservation_status(case: dict[str, Any], reservation: object) -> str:
    return str(_one(case["url"], "SELECT status FROM app.reservations WHERE id=%s", reservation)[0])


def test_a_draft_whose_reservation_was_cancelled_is_refused_before_any_money(
    migrated_database_url: str,
) -> None:
    case = _draft_of(migrated_database_url, reserved_unit(migrated_database_url))
    received = int(_deposit(case, case["deposit"])[2])
    # The draft's Security Deposit equals the money the Booking received: nothing more is due.
    _plan(case["prop"], case["lease"], case["actor"], received, "Deposit as received")
    cancel(case, CancellationResponsibility.CUSTOMER)
    assert _reservation_status(case, case["reservation"]) == "CANCELLED"
    before = (_counts(case), _deposit(case, case["deposit"]))
    rent = _due(case)
    with pytest.raises(RefusedRequest) as ended:
        _sign(case, _command(case, rent), deposits=False)
    assert ended.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    assert "Nothing was saved" in ended.value.refusal.message
    # With more of the Security Deposit due, the same.
    _plan(case["prop"], case["lease"], case["actor"], received + 10_000, "Deposit agreed")
    with pytest.raises(RefusedRequest) as owed:
        _sign(case, _command(case, rent + 10_000), deposits=False)
    assert owed.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    assert _status(case) == ("DRAFTED", "VACANT")
    # No Payment, Invoice, signature or command; the ended Reservation's Security Deposit is as
    # it was, still its own (DL-009).
    assert (_counts(case), _deposit(case, case["deposit"])) == before
    assert before[1][0] is None


def test_a_draft_whose_reservation_expired_is_refused(migrated_database_url: str) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as setup:
        found = expired_reservation(setup)
        setup.commit()
    case = _draft_of(url, found)
    # The draft's Security Deposit equals the money the Booking received: nothing more is due, so
    # no receipt step can stop it (third review: 249 signed this as a walk-in after the worker).
    received = int(_deposit(case, case["deposit"])[2])
    _plan(case["prop"], case["lease"], case["actor"], received, "Deposit as received")
    before = (_counts(case), _deposit(case, case["deposit"]))
    rent = _due(case)
    # Past its expiration day, before the expiry worker runs: the signing's own date rule.
    with pytest.raises(RefusedRequest) as passed:
        _sign(case, _command(case, rent), deposits=False)
    assert passed.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    # After the worker expired it (DL-004 cancels it): refused before any money.
    expire(case["human"], case["prop"], case["reservation"])
    with pytest.raises(RefusedRequest) as expired:
        _sign(case, _command(case, rent), deposits=False)
    assert expired.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    assert _status(case)[0] == "DRAFTED"
    assert (_counts(case), _deposit(case, case["deposit"])) == before


def test_a_draft_of_an_ended_reservation_is_refused_when_a_new_reservation_holds_the_unit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = _draft_of(url, reserved_unit(url))
    cancel(case, CancellationResponsibility.CUSTOMER)
    # The same Customer reserves the same Unit again, with a new Security Deposit.
    with psycopg.connect(url) as connection:
        _, ids = create_reservation(
            connection,
            actor_id=case["actor"],
            property_id=case["prop"],
            unit_id=case["unit"],
            customer_id=case["customer"],
        )
    second, new_deposit = ids["reservation_id"], ids["deposit_id"]
    # Nothing more is due on the old Security Deposit (third review: 249 signed with the new
    # Reservation, took its Security Deposit at 100.00 of 500.00 and cut the old one).
    received = int(_deposit(case, case["deposit"])[2])
    _plan(case["prop"], case["lease"], case["actor"], received, "Deposit as received")
    before = (_counts(case), _deposit(case, case["deposit"]), _deposit(case, new_deposit))
    rent = _due(case)
    with pytest.raises(RefusedRequest) as changed:
        _sign(case, _command(case, rent), deposits=False)
    assert changed.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    assert _status(case) == ("DRAFTED", "RESERVED")
    assert _reservation_status(case, second) == "ACTIVE"
    assert (
        _counts(case),
        _deposit(case, case["deposit"]),
        _deposit(case, new_deposit),
    ) == before


def test_a_draft_of_an_ended_reservation_is_refused_when_another_customer_holds_the_unit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = _draft_of(url, reserved_unit(url))
    received = int(_deposit(case, case["deposit"])[2])
    _plan(case["prop"], case["lease"], case["actor"], received, "Deposit as received")
    cancel(case, CancellationResponsibility.CUSTOMER)
    # Another Customer reserves the Unit.
    with psycopg.connect(url) as connection:
        other = uuid4()
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, created_by, updated_by) "
            "VALUES (%s, 'Other Customer', %s, %s)",
            (other, case["actor"], case["actor"]),
        )
        _, ids = create_reservation(
            connection,
            actor_id=case["actor"],
            property_id=case["prop"],
            unit_id=case["unit"],
            customer_id=other,
        )
    second, new_deposit = ids["reservation_id"], ids["deposit_id"]
    before = (_counts(case), _deposit(case, case["deposit"]), _deposit(case, new_deposit))
    with pytest.raises(RefusedRequest) as held:
        _sign(case, _command(case, _due(case)), deposits=False)
    assert held.value.refusal.code == "SIGNING_RESERVATION_ENDED"
    assert _status(case) == ("DRAFTED", "RESERVED")
    assert _reservation_status(case, second) == "ACTIVE"
    assert (
        _counts(case),
        _deposit(case, case["deposit"]),
        _deposit(case, new_deposit),
    ) == before


def test_a_way_of_payment_switched_off_meanwhile_is_named_and_nothing_is_saved(
    migrated_database_url: str,
) -> None:
    case = _walk_in(migrated_database_url)
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    # A way of payment the dialog showed, switched off before Sign Lease is pressed.
    method = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.payment_methods(id,code,display_name,accepted,created_by,updated_by) "
            "VALUES (%s,%s,'Switched-off test method',true,%s,%s)",
            (method, f"TEST-OFF-{method}", case["actor"], case["actor"]),
        )
        connection.execute("UPDATE app.payment_methods SET accepted=false WHERE id=%s", (method,))
    case = {**case, "method": method}
    before = _counts(case)
    with pytest.raises(RefusedRequest) as off:
        _sign(case, _command(case, _due(case) + 50_000))
    assert off.value.refusal.code == "SIGNING_PAYMENT_SOURCE_GONE"
    assert "switched off" in off.value.refusal.message
    assert "Nothing was saved" in off.value.refusal.message
    assert _status(case)[0] == "DRAFTED"
    assert _counts(case) == before


def test_a_lease_from_a_reservation_may_lower_its_deposit_or_owe_none(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    # The Booking received 100.00 of 500.00; the draft lowers the Security Deposit to 300.00.
    lower = _draft_of(url, reserved_unit(url))
    _plan(lower["prop"], lower["lease"], lower["actor"], 30_000, "Agreed lower deposit")
    result = _sign(lower, _command(lower, _due(lower) + 20_000), deposits=False)
    assert result["deposit_id"] == str(lower["deposit"]) and result["deposit_usd_cents"] == 20_000
    assert _deposit(lower, lower["deposit"]) == (lower["lease"], 30_000, 30_000)
    assert _one(
        url,
        "SELECT adjustment_type, amount_usd_cents FROM app.deposit_required_amount_adjustments "
        "WHERE deposit_id=%s",
        lower["deposit"],
    ) == ("DECREASE", 20_000)
    # The draft's Security Deposit equals the money received: only the Initial Rent is due, and
    # the Reservation's Security Deposit becomes the Lease's.
    paid = _draft_of(url, reserved_unit(url))
    _plan(paid["prop"], paid["lease"], paid["actor"], 10_000, "Deposit as received")
    rent = _due(paid)
    result = _sign(paid, _command(paid, rent), deposits=False)
    assert (result["total_usd_cents"], result["deposit_usd_cents"]) == (rent, 0)
    assert result["deposit_receipt_id"] is None
    assert _deposit(paid, paid["deposit"]) == (paid["lease"], 10_000, 10_000)
    assert _status(paid) == ("SIGNED", "OCCUPIED")
    assert _reservation_status(paid, paid["reservation"]) == "COMPLETED"


def test_a_walk_in_draft_takes_the_customers_active_reservation_and_its_deposit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = _draft_of(url, reserved_unit(url), names_deposit=False)
    _plan(case["prop"], case["lease"], case["actor"], 50_000, "Deposit agreed")
    result = _sign(case, _command(case, _due(case) + 40_000), deposits=False)
    assert result["reservation_id"] == str(case["reservation"])
    assert result["deposit_id"] == str(case["deposit"])
    assert _deposit(case, case["deposit"]) == (case["lease"], 50_000, 50_000)
    assert _one(url, "SELECT count(*) FROM app.deposits WHERE lease_id=%s", case["lease"]) == (1,)


def test_an_overlapping_signed_lease_is_refused_not_unknown(migrated_database_url: str) -> None:
    first = _walk_in(migrated_database_url)
    start = _one(
        migrated_database_url, "SELECT start_date FROM app.leases WHERE id=%s", first["lease"]
    )[0]
    with psycopg.connect(migrated_database_url) as connection:
        second = create_draft(
            connection,
            actor_id=first["actor"],
            unit_id=first["unit"],
            primary_tenant_id=first["customer"],
            start_date=start,
            end_date=month_end(start + timedelta(days=200)),
            signed=False,
        )
    _plan(first["prop"], first["lease"], first["actor"], 50_000)
    _plan(first["prop"], second, first["actor"], 50_000)
    _sign(first, _command(first, _due(first) + 50_000))
    case = {**first, "lease": second}
    before = _counts(case)
    with pytest.raises(RefusedRequest) as taken:
        _sign(case, _command(case, _due(case) + 50_000))
    assert taken.value.refusal.code == "SIGNING_DATES_TAKEN"
    assert "Nothing was saved" in taken.value.refusal.message
    assert _status(case)[0] == "DRAFTED"
    assert _counts(case) == before


def test_sign_lease_reservation_check_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "20270407_257"
    revision = scripts.get_revision("20270331_250")
    assert revision is not None and revision.down_revision == "20270330_249"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
