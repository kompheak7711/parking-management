"""Migration 20270330_249 (V1-060 B7, DL-108): Sign Lease and its money in one transaction.

The Payment and its Receipt, the signatures, the signing, the draft's Security Deposit, the Initial
Rent Invoice paid by name and the rest of the money in the Security Deposit are saved together, or
nothing is (AGENTS.md: database transactions for multi-step financial operations). The same key
with the same request answers the same; the same key with anything else is refused.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import database_instant, seed_method
from property_rental.api_refusals import RefusedRequest
from property_rental.billing import month_end
from property_rental.lease_signing_api import (
    LeaseSigningConflict,
    PostgresLeaseSigningFlow,
    SignWithPaymentCommand,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_lifecycle_migration import draft_command
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_lease_signing_reservation_migration import business_date, leases, reserved_unit
from unit_type_support import seeded_unit_type

PLAN = "SELECT app.set_lease_planned_security_deposit(%s,%s,%s,%s,%s,%s,%s)"
REASON = "Every Signer signed the paper Lease"


def _one(url: str, query: str, *values: object) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(query, values).fetchone()
    assert row is not None
    return row


def _plan(prop: UUID, lease: UUID, actor: UUID, cents: int, reason: str = "Draft terms") -> None:
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(PLAN, (prop, lease, uuid4(), actor, cents, reason, "leases.draft"))


def _walk_in(url: str, *, days_ago: int = 0, signed: bool = False) -> dict[str, Any]:
    """A walk-in draft starting today in Phnom Penh; its Primary Tenant has not signed yet."""
    with psycopg.connect(url) as connection:
        actor, prop, unit, customer, _ = setup_sources(connection)
        today = cast(
            date,
            (
                connection.execute(
                    "SELECT timezone(timezone_name, clock_timestamp())::date "
                    "FROM app.properties WHERE id=%s",
                    (prop,),
                ).fetchone()
                or (None,)
            )[0],
        )
        begin = today - timedelta(days=days_ago)
        lease = create_draft(
            connection,
            actor_id=actor,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=begin,
            end_date=month_end(begin + timedelta(days=400)),
            signed=signed,
        )
        method = seed_method(connection, actor)
    return {
        "url": url,
        "actor": actor,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "lease": lease,
        "method": method,
    }


def _flow() -> PostgresLeaseSigningFlow:
    return PostgresLeaseSigningFlow(runtime_database_url(), financial_database_url())


def _due(case: dict[str, Any]) -> int:
    preview = _flow().preview(case["prop"], case["lease"])
    return int(cast(dict[str, Any], preview["initial"])["total_usd_cents"])


def _unsigned(case: dict[str, Any]) -> tuple[UUID, ...]:
    with psycopg.connect(case["url"]) as connection:
        rows = connection.execute(
            "SELECT id FROM app.lease_signers WHERE lease_id=%s AND signed_at IS NULL ORDER BY id",
            (case["lease"],),
        ).fetchall()
    return tuple(UUID(str(row[0])) for row in rows)


def _version(case: dict[str, Any]) -> int:
    return int(_one(case["url"], "SELECT version FROM app.leases WHERE id=%s", case["lease"])[0])


def _command(case: dict[str, Any], amount: int, **changes: Any) -> SignWithPaymentCommand:
    with psycopg.connect(case["url"]) as connection:
        at = database_instant(connection) - timedelta(seconds=1)
    command = SignWithPaymentCommand(
        idempotency_key=uuid4(),
        expected_version=_version(case),
        signer_ids=_unsigned(case),
        reason=REASON,
        payment_method_id=case["method"],
        received_amount_minor=amount,
        received_at=at,
        evidence_reference="Cash received, Cash",
        payer_intent_memo="Money received at signing the Lease",
    )
    return replace(command, **changes)


def _sign(
    case: dict[str, Any], command: SignWithPaymentCommand, *, deposits: bool = True
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _flow().sign_with_payment(case["prop"], case["lease"], command, case["actor"], deposits),
    )


def _counts(case: dict[str, Any]) -> tuple[int, ...]:
    """Payments and Invoices of the Primary Tenant, Deposits and commands of the Lease."""
    row = _one(
        case["url"],
        "SELECT (SELECT count(*) FROM app.payments WHERE payer_customer_id=%s),"
        "(SELECT count(*) FROM app.invoices WHERE customer_id=%s),"
        "(SELECT count(*) FROM app.deposits WHERE lease_id=%s),"
        "(SELECT count(*) FROM app.lease_signing_payment_commands WHERE lease_id=%s),"
        "(SELECT count(*) FROM app.lease_signers WHERE lease_id=%s AND signed_at IS NOT NULL)",
        case["customer"],
        case["customer"],
        case["lease"],
        case["lease"],
        case["lease"],
    )
    return tuple(int(value) for value in row)


def _status(case: dict[str, Any]) -> tuple[str, str]:
    row = _one(
        case["url"],
        "SELECT lease.status, unit.status FROM app.leases lease "
        "JOIN app.units unit ON unit.id=lease.unit_id WHERE lease.id=%s",
        case["lease"],
    )
    return str(row[0]), str(row[1])


def test_a_walk_in_lease_is_signed_with_its_money_in_one_step(migrated_database_url: str) -> None:
    case = _walk_in(migrated_database_url)
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    rent = _due(case)
    before = _counts(case)
    command = _command(case, rent + 50_000)
    result = _sign(case, command)

    assert _status(case) == ("SIGNED", "OCCUPIED")
    assert result["total_usd_cents"] == rent + 50_000
    assert (result["rent_usd_cents"], result["deposit_usd_cents"]) == (rent, 50_000)
    assert result["receipt_number"]
    url = case["url"]
    assert _one(
        url, "SELECT invoice_number FROM app.invoices WHERE id=%s", result["invoice_id"]
    ) == (result["invoice_number"],)
    # The Initial Rent Invoice is paid in full by name with this Payment.
    assert _one(url, "SELECT status FROM app.invoices WHERE id=%s", result["invoice_id"]) == (
        "PAID",
    )
    assert _one(
        url,
        "SELECT between_invoice_basis, customer_designation_reference, amount_usd_cents "
        "FROM app.payment_allocations WHERE payment_id=%s",
        result["payment_id"],
    ) == ("CUSTOMER_DESIGNATED", "Sign Lease: the Initial Rent Invoice (DL-100)", rent)
    # The walk-in Security Deposit is made at the draft's amount and holds the rest.
    deposit = _one(
        url,
        "SELECT (s->>'required_usd_cents')::bigint,(s->>'received_usd_cents')::bigint "
        "FROM (SELECT app.deposit_snapshot(%s) AS s) AS d",
        result["deposit_id"],
    )
    assert deposit == (50_000, 50_000)
    assert _one(url, "SELECT app.payment_available_value(%s)", result["payment_id"]) == (0,)
    assert _counts(case) == (
        before[0] + 1,
        before[1] + 1,
        before[2] + 1,
        before[3] + 1,
        before[4] + 1,
    )

    # The same press again (no answer the first time) saves nothing new.
    assert _sign(case, command) == result
    assert _counts(case)[0:4] == (before[0] + 1, before[1] + 1, before[2] + 1, before[3] + 1)
    # The same key with another request is refused, and nothing is saved.
    with pytest.raises(RefusedRequest) as reused:
        _sign(case, replace(command, evidence_reference="Another receipt book page"))
    assert reused.value.refusal.code == "SIGNING_KEY_REUSED"
    # A new key cannot sign it again: the Lease is no longer a draft.
    with pytest.raises((RefusedRequest, LeaseSigningConflict)):
        _sign(case, _command(case, rent + 50_000))
    assert _counts(case)[0:4] == (before[0] + 1, before[1] + 1, before[2] + 1, before[3] + 1)


def test_the_money_pays_the_new_initial_rent_invoice_never_an_older_one(
    migrated_database_url: str,
) -> None:
    first = _walk_in(migrated_database_url, signed=True)
    url = first["url"]
    # The Customer already rents another Unit and owes its Initial Rent Invoice.
    with psycopg.connect(url) as connection:
        sign_lease(connection, first["lease"], first["actor"])
    older = uuid4()
    start = cast(
        date, _one(url, "SELECT start_date FROM app.leases WHERE id=%s", first["lease"])[0]
    )
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute(
            "SELECT app.generate_rent_service_invoice"
            "(%s,%s,%s,%s,%s,%s,NULL,'INITIAL',%s,clock_timestamp(),%s,NULL)",
            (
                first["prop"],
                uuid4(),
                hashlib.sha256(older.bytes).hexdigest(),
                older,
                f"RENT-I-OLD-{older.hex[:12]}",
                first["lease"],
                start,
                first["actor"],
            ),
        )
    with psycopg.connect(url) as connection:
        unit = uuid4()
        connection.execute(
            "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,created_by,"
            "updated_by) VALUES (%s,%s,%s,'1',%s,'VACANT',%s,%s)",
            (
                unit,
                first["prop"],
                f"SIGN-{unit.hex[:12]}",
                seeded_unit_type(connection, first["prop"]),
                first["actor"],
                first["actor"],
            ),
        )
        lease = create_draft(
            connection,
            actor_id=first["actor"],
            unit_id=unit,
            primary_tenant_id=first["customer"],
            start_date=start,
            end_date=month_end(start + timedelta(days=400)),
            signed=False,
        )
    case = {**first, "unit": unit, "lease": lease}
    _plan(case["prop"], lease, case["actor"], 30_000)
    rent = _due(case)
    result = _sign(case, _command(case, rent + 30_000))
    assert _one(url, "SELECT status FROM app.invoices WHERE id=%s", older) == ("UNPAID",)
    assert _one(url, "SELECT status FROM app.invoices WHERE id=%s", result["invoice_id"]) == (
        "PAID",
    )
    assert _one(
        url,
        "SELECT (app.deposit_snapshot(%s)->>'received_usd_cents')::bigint",
        result["deposit_id"],
    ) == (30_000,)


def test_nothing_is_saved_when_the_signing_is_refused_after_the_money_step(
    migrated_database_url: str,
) -> None:
    case = _walk_in(migrated_database_url)
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    rent = _due(case)
    before = _counts(case)
    # The Unit went out of service meanwhile: the signing step refuses after the Payment step,
    # in the same transaction, so the Payment is not kept either.
    with psycopg.connect(case["url"]) as connection:
        connection.execute(
            "UPDATE app.units SET status='OUT_OF_SERVICE', version=version+1, "
            "updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
            (case["actor"], case["unit"]),
        )
    with pytest.raises(RefusedRequest) as refused:
        _sign(case, _command(case, rent + 50_000))
    assert refused.value.refusal.code == "SIGNING_UNIT_NOT_FREE"
    assert _counts(case) == before
    assert _status(case) == ("DRAFTED", "OUT_OF_SERVICE")


def test_each_problem_found_before_the_money_saves_nothing(migrated_database_url: str) -> None:
    case = _walk_in(migrated_database_url)
    rent = _due(case)
    before = _counts(case)
    # A walk-in draft needs its Security Deposit first (DL-101).
    with pytest.raises(RefusedRequest) as missing:
        _sign(case, _command(case, rent))
    assert missing.value.refusal.code == "SIGNING_DEPOSIT_MISSING"
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    # Not the exact total due at signing.
    with pytest.raises(RefusedRequest) as total:
        _sign(case, _command(case, rent + 49_999))
    assert total.value.refusal.code == "SIGNING_TOTAL_CHANGED"
    # Not every Signer ticked.
    with pytest.raises(RefusedRequest) as signers:
        _sign(case, _command(case, rent + 50_000, signer_ids=()))
    assert signers.value.refusal.code == "SIGNING_SIGNERS_CHANGED"
    # The Lease changed after the screen read it.
    with pytest.raises(LeaseSigningConflict):
        _sign(case, _command(case, rent + 50_000, expected_version=_version(case) + 1))
    # Without the right to manage deposits, a walk-in Lease's Security Deposit cannot be made.
    with pytest.raises(RefusedRequest) as right:
        _sign(case, _command(case, rent + 50_000), deposits=False)
    assert right.value.refusal.code == "SIGNING_NO_DEPOSIT_RIGHT"
    assert _counts(case) == before
    assert _status(case)[0] == "DRAFTED"


def test_a_passed_initial_rent_due_date_is_refused_before_any_money(
    migrated_database_url: str,
) -> None:
    case = _walk_in(migrated_database_url, days_ago=10)
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    rent = _due(case)
    before = _counts(case)
    with pytest.raises(RefusedRequest) as passed:
        _sign(case, _command(case, rent + 50_000))
    assert passed.value.refusal.code == "INITIAL_RENT_DUE_DATE_PASSED"
    assert _counts(case) == before


def test_a_lease_from_a_reservation_takes_the_rest_of_its_deposit(
    migrated_database_url: str,
) -> None:
    actor, prop, unit, customer, reservation, deposit = reserved_unit(migrated_database_url)
    service, who = leases(actor, prop)
    today = business_date(migrated_database_url, prop)
    draft = replace(
        draft_command(
            unit, customer, start_date=today, end_date=month_end(today + timedelta(days=365))
        ),
        security_deposit_id=deposit,
    )
    service.draft_with_terms(draft, actor=who)
    with psycopg.connect(migrated_database_url) as connection:
        method = seed_method(connection, actor)
    case = {
        "url": migrated_database_url,
        "actor": actor,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "lease": draft.lease_id,
        "method": method,
    }
    # The draft raises the Security Deposit from 500.00 to 600.00; 100.00 came with the Booking.
    _plan(prop, draft.lease_id, actor, 60_000, "Rent went up")
    rent = _due(case)
    result = _sign(case, _command(case, rent + 50_000), deposits=False)
    url = migrated_database_url
    assert result["reservation_id"] == str(reservation)
    assert result["deposit_id"] == str(deposit) and result["deposit_usd_cents"] == 50_000
    assert _one(url, "SELECT status FROM app.reservations WHERE id=%s", reservation) == (
        "COMPLETED",
    )
    assert _one(
        url,
        "SELECT (s->>'required_usd_cents')::bigint,(s->>'received_usd_cents')::bigint "
        "FROM (SELECT app.deposit_snapshot(%s) AS s) AS d",
        deposit,
    ) == (60_000, 60_000)
    assert _one(
        url,
        "SELECT adjustment_type, amount_usd_cents FROM app.deposit_required_amount_adjustments "
        "WHERE deposit_id=%s",
        deposit,
    ) == ("INCREASE", 10_000)
    assert _one(url, "SELECT status FROM app.invoices WHERE id=%s", result["invoice_id"]) == (
        "PAID",
    )


def test_a_renewal_pays_only_its_initial_rent(migrated_database_url: str) -> None:
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
    rent = _due(case)
    result = _sign(case, _command(case, rent), deposits=False)
    assert (result["deposit_usd_cents"], result["deposit_id"]) == (0, None)
    assert _status(case)[0] == "SIGNED"
    assert _one(url, "SELECT count(*) FROM app.deposits WHERE lease_id=%s", renewal) == (0,)


def test_the_command_is_the_financial_role_s_and_its_records_never_change(
    migrated_database_url: str,
) -> None:
    case = _walk_in(migrated_database_url)
    _plan(case["prop"], case["lease"], case["actor"], 50_000)
    result = _sign(case, _command(case, _due(case) + 50_000))
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.sign_lease_with_payment(%s,%s,%s,%s,%s,1,'{}',%s,'{}',true)",
                (case["prop"], case["actor"], uuid4(), "0" * 64, case["lease"], REASON),
            )
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM app.lease_signing_payment_commands")
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.lease_signing_payment_commands SET recorded_at=now() WHERE lease_id=%s",
                (case["lease"],),
            )
        connection.rollback()
        with pytest.raises(psycopg.Error):
            connection.execute(
                "DELETE FROM app.lease_signing_payment_commands WHERE payment_id=%s",
                (result["payment_id"],),
            )


def test_a_planned_deposit_save_used_again_for_another_amount_is_refused(
    migrated_database_url: str,
) -> None:
    case = _walk_in(migrated_database_url)
    save = uuid4()
    values = (
        case["prop"],
        case["lease"],
        save,
        case["actor"],
        50_000,
        "Draft terms",
        "leases.draft",
    )
    with psycopg.connect(runtime_database_url()) as connection:
        assert connection.execute(PLAN, values).fetchone() == (50_000,)
        assert connection.execute(PLAN, values).fetchone() == (50_000,)
        connection.commit()
        with pytest.raises(psycopg.errors.UniqueViolation) as reused:
            connection.execute(
                PLAN,
                (
                    case["prop"],
                    case["lease"],
                    save,
                    case["actor"],
                    70_000,
                    "Draft terms",
                    "leases.draft",
                ),
            )
    assert reused.value.diag.message_primary == (
        "This Security Deposit save was already used for another amount"
    )
    assert _flow().preview(case["prop"], case["lease"])["planned_security_deposit_usd_cents"] == (
        50_000
    )


def test_sign_lease_in_one_step_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20270330_249")
    assert revision is not None and revision.down_revision == "20270329_248"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
