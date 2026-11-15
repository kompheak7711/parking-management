"""Real PostgreSQL coverage of the Pet Deposit received at Sign Lease (clean-up step D4, DL-234,
migration 20270731_397; BR-DEP-010, BR-DEP-006).

The owner decided on 12 November 2026 (DL-226) that the Pet Deposit for a pet kept from the start
is received at Sign Lease, with the Security Deposit and the Initial Rent. Before, it was due
within five days after the Lease Start Date and was made and received by hand after signing.

The draft Lease now records the Pet Deposit amount when its terms ask for one, as it records the
Security Deposit (DL-101). Sign Lease takes the full total in one Payment and makes the Pet
Deposit with its receipt in the same step.

The helpers are those of ``test_sign_lease_in_one_step_migration.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.api_refusals import RefusedRequest
from property_rental.billing import month_end
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_migration import create_draft, sign_lease
from test_sign_lease_in_one_step_migration import (
    _command,
    _counts,
    _due,
    _flow,
    _one,
    _plan,
    _sign,
    _status,
    _walk_in,
)

REVISION = "20270731_397"
PLAN_PET = "SELECT app.set_lease_planned_pet_deposit(%s,%s,%s,%s,%s,%s,%s)"


def _pet(url: str, lease: UUID, actor: UUID, *, deposit: bool = True) -> UUID:
    """The draft's pet term: an approved pet, with or without a Pet Deposit in the terms."""
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "SELECT %s,lease.id,lease.start_date,%s,'One small dog',clock_timestamp(),%s "
            "FROM app.leases AS lease WHERE lease.id=%s",
            (approval, deposit, actor, lease),
        )
    return approval


def _plan_pet(
    case: dict[str, Any], cents: int, *, plan: UUID | None = None, reason: str = "Draft terms"
) -> int:
    return _flow().set_planned_pet_deposit(
        case["prop"], case["lease"], plan or uuid4(), case["actor"], cents, reason
    )


def _refusal(url: str, sql: str, *parameters: object) -> tuple[str | None, str | None]:
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(sql, parameters)
    return failure.value.sqlstate, failure.value.diag.message_primary


def test_the_migration_follows_the_late_payment_invoice_step_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "20270730_396"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_sign_lease_receives_the_pet_deposit_with_the_security_deposit_and_the_initial_rent(
    migrated_database_url: str,
) -> None:
    """Initial Rent + Security Deposit 500.00 + Pet Deposit 100.00 in one Payment; the Pet
    Deposit is made for the approved pet and is received in full."""
    url = migrated_database_url
    case = _walk_in(url)
    approval = _pet(url, case["lease"], case["actor"])
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    assert _plan_pet(case, 10_000) == 10_000
    rent = _due(case)
    preview = _flow().preview(case["prop"], case["lease"])
    assert preview["pet_deposit_required"] is True
    assert preview["planned_pet_deposit_usd_cents"] == 10_000
    before = _counts(case)

    command = _command(case, rent + 50_000 + 10_000)
    result = _sign(case, command)

    assert _status(case) == ("SIGNED", "OCCUPIED")
    assert result["total_usd_cents"] == rent + 60_000
    assert (
        result["rent_usd_cents"],
        result["deposit_usd_cents"],
        result["pet_deposit_usd_cents"],
    ) == (rent, 50_000, 10_000)
    pet = _one(
        url,
        "SELECT deposit.id,deposit.pet_approval_id,deposit.customer_id,"
        "(app.deposit_snapshot(deposit.id)->>'required_usd_cents')::bigint,"
        "(app.deposit_snapshot(deposit.id)->>'received_usd_cents')::bigint "
        "FROM app.deposits AS deposit WHERE deposit.lease_id=%s AND deposit.deposit_type='PET'",
        case["lease"],
    )
    assert pet == (UUID(result["pet_deposit_id"]), approval, case["customer"], 10_000, 10_000)
    assert result["pet_deposit_receipt_id"]
    # The Security Deposit and the Initial Rent Invoice are as before; nothing waits.
    assert _one(
        url,
        "SELECT (app.deposit_snapshot(%s)->>'received_usd_cents')::bigint",
        result["deposit_id"],
    ) == (50_000,)
    assert _one(url, "SELECT status FROM app.invoices WHERE id=%s", result["invoice_id"]) == (
        "PAID",
    )
    assert _one(url, "SELECT app.payment_available_value(%s)", result["payment_id"]) == (0,)
    # One Payment, one Invoice, two Deposits, one command, one more signature.
    assert _counts(case) == (
        before[0] + 1,
        before[1] + 1,
        before[2] + 2,
        before[3] + 1,
        before[4] + 1,
    )
    # The same press again saves nothing new.
    assert _sign(case, command) == result
    assert _counts(case)[0:4] == (before[0] + 1, before[1] + 1, before[2] + 2, before[3] + 1)


def test_a_draft_with_a_pet_deposit_in_its_terms_is_not_signed_without_the_amount_or_the_right(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = _walk_in(url)
    _pet(url, case["lease"], case["actor"])
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    rent = _due(case)
    before = _counts(case)
    preview = _flow().preview(case["prop"], case["lease"])
    assert (preview["pet_deposit_required"], preview["planned_pet_deposit_usd_cents"]) == (
        True,
        None,
    )

    with pytest.raises(RefusedRequest) as missing:
        _sign(case, _command(case, rent + 50_000))
    assert missing.value.refusal.code == "SIGNING_PET_DEPOSIT_MISSING"
    _plan_pet(case, 10_000)
    # The total without the Pet Deposit is no longer the total due at signing.
    with pytest.raises(RefusedRequest) as total:
        _sign(case, _command(case, rent + 50_000))
    assert total.value.refusal.code == "SIGNING_TOTAL_CHANGED"
    # Without the right to manage deposits, the Pet Deposit cannot be made.
    with pytest.raises(RefusedRequest) as right:
        _sign(case, _command(case, rent + 60_000), deposits=False)
    assert right.value.refusal.code == "SIGNING_NO_DEPOSIT_RIGHT"
    assert _counts(case) == before
    assert _status(case)[0] == "DRAFTED"


def test_a_draft_without_a_pet_deposit_in_its_terms_is_signed_as_before(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    # No pet at all.
    plain = _walk_in(url)
    _plan(plain["prop"], plain["lease"], plain["actor"], 50_000)
    preview = _flow().preview(plain["prop"], plain["lease"])
    assert (preview["pet_deposit_required"], preview["planned_pet_deposit_usd_cents"]) == (
        False,
        None,
    )
    rent = _due(plain)
    result = _sign(plain, _command(plain, rent + 50_000))
    assert (result["pet_deposit_usd_cents"], result["pet_deposit_id"]) == (0, None)
    assert _one(
        url,
        "SELECT count(*) FROM app.deposits WHERE lease_id=%s AND deposit_type='PET'",
        plain["lease"],
    ) == (0,)

    # An approved pet whose Lease terms ask for no Pet Deposit (BR-DEP-007).
    free = _walk_in(url)
    _pet(url, free["lease"], free["actor"], deposit=False)
    _plan(free["prop"], free["lease"], free["actor"], 50_000)
    assert _flow().preview(free["prop"], free["lease"])["pet_deposit_required"] is False
    rent = _due(free)
    result = _sign(free, _command(free, rent + 50_000))
    assert (result["pet_deposit_usd_cents"], result["pet_deposit_id"]) == (0, None)


def test_the_pet_deposit_amount_is_recorded_only_on_a_draft_whose_terms_ask_for_it(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = _walk_in(url)
    values = (case["prop"], case["lease"], uuid4(), case["actor"], 10_000, "Draft terms")

    # No approved pet with a Pet Deposit in the terms.
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(psycopg.Error) as no_pet:
            runtime.execute(PLAN_PET, (*values, "leases.draft"))
        runtime.rollback()
    assert (no_pet.value.sqlstate, no_pet.value.diag.message_primary) == (
        "55000",
        "The Lease terms ask for no Pet Deposit",
    )

    _pet(url, case["lease"], case["actor"])
    # A wrong amount, reason or right.
    for amount, reason, right in (
        (0, "Draft terms", "leases.draft"),
        (10_000, " ", "leases.draft"),
        (10_000, "Draft terms", "deposits.manage"),
    ):
        assert _refusal(
            runtime_database_url(),
            PLAN_PET,
            case["prop"],
            case["lease"],
            uuid4(),
            case["actor"],
            amount,
            reason,
            right,
        ) == ("22023", "Planned Pet Deposit evidence is invalid")

    # Each save keeps its history; the latest wins; the same save again changes nothing.
    first = uuid4()
    assert _plan_pet(case, 10_000, plan=first) == 10_000
    assert _plan_pet(case, 10_000, plan=first) == 10_000
    assert _plan_pet(case, 15_000, reason="The owner agreed 150.00") == 15_000
    assert _one(
        url,
        "SELECT array_agg(required_usd_cents ORDER BY recorded_at,id) "
        "FROM app.lease_planned_pet_deposits WHERE lease_id=%s",
        case["lease"],
    ) == ([10_000, 15_000],)
    # A save used again for another amount is refused.
    assert _refusal(
        runtime_database_url(),
        PLAN_PET,
        case["prop"],
        case["lease"],
        first,
        case["actor"],
        20_000,
        "Draft terms",
        "leases.draft",
    ) == ("23505", "This Pet Deposit save was already used for another amount")
    assert _one(
        url,
        "SELECT count(*) FROM app.audit_events WHERE lease_id=%s "
        "AND action='lease.pet_deposit.planned'",
        case["lease"],
    ) == (2,)
    # The records never change, and only the runtime role may save.
    assert _refusal(
        url, "UPDATE app.lease_planned_pet_deposits SET reason='x' WHERE lease_id=%s", case["lease"]
    )[0] in {"55000", "P0001", "23514"}
    with psycopg.connect(financial_database_url()) as financial:
        assert financial.execute(
            "SELECT has_function_privilege(current_user,%s::regprocedure,'EXECUTE')",
            ("app.set_lease_planned_pet_deposit(uuid,uuid,uuid,uuid,bigint,text,text)",),
        ).fetchone() == (False,)

    # A signed Lease takes no planned amount any more.
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    rent = _due(case)
    _sign(case, _command(case, rent + 50_000 + 15_000))
    assert _refusal(
        runtime_database_url(),
        PLAN_PET,
        case["prop"],
        case["lease"],
        uuid4(),
        case["actor"],
        20_000,
        "Draft terms",
        "leases.draft",
    ) == ("55000", "Only a drafted Lease takes a planned Pet Deposit")


def test_a_renewal_takes_no_pet_deposit_at_signing(migrated_database_url: str) -> None:
    """A renewal pays only its Initial Rent, as before (DL-066): the Pet Deposit of a pet on a
    renewal stays a step by hand."""
    first = _walk_in(migrated_database_url, signed=True)
    url = first["url"]
    with psycopg.connect(url) as connection:
        sign_lease(connection, first["lease"], first["actor"])
        end = cast(
            date, _one(url, "SELECT end_date FROM app.leases WHERE id=%s", first["lease"])[0]
        )
        renewal = create_draft(
            connection,
            actor_id=first["actor"],
            unit_id=first["unit"],
            primary_tenant_id=first["customer"],
            start_date=end + timedelta(days=1),
            end_date=month_end(end + timedelta(days=370)),
            signed=False,
            predecessor_lease_id=first["lease"],
        )
    case = {**first, "lease": renewal}
    _pet(url, renewal, case["actor"])
    assert _flow().preview(case["prop"], renewal)["pet_deposit_required"] is False
    assert _refusal(
        runtime_database_url(),
        PLAN_PET,
        case["prop"],
        renewal,
        uuid4(),
        case["actor"],
        10_000,
        "Draft terms",
        "leases.draft",
    ) == ("55000", "A renewal Lease takes no Pet Deposit at signing")
    rent = _due(case)
    result = _sign(case, _command(case, rent), deposits=False)
    assert (result["pet_deposit_usd_cents"], result["pet_deposit_id"]) == (0, None)
    assert _status(case)[0] == "SIGNED"
