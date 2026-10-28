"""Migration 20270326_245 (V1-060 B6, DL-101): a Lease from a Reservation records its Security
Deposit on the draft, never below the money received, and Sign Lease applies it after signing."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.billing import month_end
from property_rental.lease import LEASE_SIGN_CAPABILITY, LeaseSignCommand
from property_rental.lease_signing_api import PostgresLeaseSigningFlow
from test_invoice_migration import financial_database_url
from test_lease_lifecycle_migration import database_now, draft_command, signature_command
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_lease_signing_reservation_migration import business_date, leases, reserved_unit
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

PLAN = "SELECT app.set_lease_planned_security_deposit(%s,%s,%s,%s,%s,%s,%s)"
HELD = "SELECT app.lease_held_security_deposit(%s,%s)"
APPLY = "SELECT app.apply_lease_planned_security_deposit(%s,%s,%s,%s,%s)"


def _plan(url: str, prop: UUID, lease: UUID, actor: UUID, cents: int, reason: str) -> object:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            PLAN, (prop, lease, uuid4(), actor, cents, reason, "leases.draft")
        ).fetchone()
    assert row is not None
    return row[0]


def _apply(prop: UUID, lease: UUID, adjustment: UUID, actor: UUID) -> object:
    """The step of app.sign_lease_with_payment (DL-108) that applies the draft's amount."""
    with psycopg.connect(financial_database_url()) as connection:
        row = connection.execute(
            APPLY, (prop, lease, adjustment, actor, LEASE_SIGN_CAPABILITY)
        ).fetchone()
    assert row is not None
    return row[0]


def test_a_draft_from_a_reservation_records_its_deposit_and_signing_applies_it(
    migrated_database_url: str,
) -> None:
    actor, prop, unit, customer, reservation, deposit = reserved_unit(migrated_database_url)
    service, who = leases(actor, prop)
    today = business_date(migrated_database_url, prop)
    draft = replace(
        draft_command(
            unit,
            customer,
            start_date=today - timedelta(days=1),
            end_date=month_end(today + timedelta(days=365)),
        ),
        security_deposit_id=deposit,
    )
    service.draft_with_terms(draft, actor=who)
    lease = draft.lease_id
    runtime = runtime_database_url()
    with psycopg.connect(runtime) as connection:
        held = connection.execute(HELD, (prop, lease)).fetchone()
    assert held is not None
    assert held[0] == {
        "deposit_id": str(deposit),
        "required_usd_cents": 50_000,
        "received_usd_cents": 10_000,
    }
    # Never below the money already received with the Reservation.
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        _plan(runtime, prop, lease, actor, 9_999, "Too low")
    assert refused.value.diag.message_primary == (
        "The Security Deposit cannot be less than the money already received"
    )
    # The Reservation's own amount is still recorded: it is a Lease term like the Rent.
    assert _plan(runtime, prop, lease, actor, 50_000, "Security Deposit on the draft") == 50_000
    assert _plan(runtime, prop, lease, actor, 60_000, "Rent went up") == 60_000
    flow = PostgresLeaseSigningFlow(runtime, financial_database_url())
    preview = flow.preview(prop, lease)
    assert preview["planned_security_deposit_usd_cents"] == 60_000
    assert cast(dict[str, object], preview["held_security_deposit"])["required_usd_cents"] == 50_000
    with pytest.raises(psycopg.Error) as early:
        _apply(prop, lease, uuid4(), actor)
    assert early.value.diag.message_primary == "Sign the Lease before its Security Deposit changes"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_required_amount_adjustments WHERE deposit_id=%s",
            (deposit,),
        ).fetchone() == (0,)

    service.record_signature(signature_command(lease, draft.primary_signer_id, 1), actor=who)
    service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease,
            expected_version=2,
            signed_at=database_now(),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=reservation,
        ),
        actor=who,
    )
    adjustment = uuid4()
    assert _apply(prop, lease, adjustment, actor) == {
        "changed": True,
        "required_usd_cents": 60_000,
    }
    # The same request again replays; another request finds it already applied.
    assert _apply(prop, lease, adjustment, actor) == {
        "changed": True,
        "required_usd_cents": 60_000,
    }
    assert _apply(prop, lease, uuid4(), actor) == {
        "changed": False,
        "required_usd_cents": 60_000,
    }
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT adjustment_type,amount_usd_cents,reason,authorization_reference "
            "FROM app.deposit_required_amount_adjustments WHERE deposit_id=%s",
            (deposit,),
        ).fetchall() == [("INCREASE", 10_000, "Rent went up", "leases.sign")]
        assert connection.execute(
            "SELECT (app.deposit_snapshot(%s)->>'outstanding_required_usd_cents')::bigint",
            (deposit,),
        ).fetchone() == (50_000,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action='lease.security_deposit.applied' AND lease_id=%s",
            (lease,),
        ).fetchone() == (1,)
    with psycopg.connect(runtime) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.apply_lease_planned_security_deposit(%s,%s,%s,%s,%s)",
                (prop, lease, uuid4(), actor, "leases.sign"),
            )


def test_a_lower_amount_on_the_draft_becomes_a_decrease_at_signing(
    migrated_database_url: str,
) -> None:
    actor, prop, unit, customer, reservation, deposit = reserved_unit(migrated_database_url)
    service, who = leases(actor, prop)
    today = business_date(migrated_database_url, prop)
    draft = replace(
        draft_command(
            unit,
            customer,
            start_date=today - timedelta(days=1),
            end_date=month_end(today + timedelta(days=365)),
        ),
        security_deposit_id=deposit,
    )
    service.draft_with_terms(draft, actor=who)
    runtime = runtime_database_url()
    assert _plan(runtime, prop, draft.lease_id, actor, 40_000, "Agreed lower") == 40_000
    service.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=reservation,
        ),
        actor=who,
    )
    assert _apply(prop, draft.lease_id, uuid4(), actor) == {
        "changed": True,
        "required_usd_cents": 40_000,
    }
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT adjustment_type,amount_usd_cents FROM app.deposit_required_amount_adjustments "
            "WHERE deposit_id=%s",
            (deposit,),
        ).fetchall() == [("DECREASE", 10_000)]


def test_a_walk_in_lease_has_no_held_deposit_and_nothing_to_apply(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor, prop, unit, customer, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=actor,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=date(2027, 5, 1),
            end_date=date(2028, 4, 30),
        )
    runtime = runtime_database_url()
    with psycopg.connect(runtime) as connection:
        assert connection.execute(HELD, (prop, lease)).fetchone() == (None,)
    assert _plan(runtime, prop, lease, actor, 80_000, "Walk-in") == 80_000
    with psycopg.connect(migrated_database_url) as connection:
        sign_lease(connection, lease, actor)
    assert _apply(prop, lease, uuid4(), actor) == {
        "changed": False,
        "required_usd_cents": None,
    }
