"""Termination for an unpaid Initial obligation: never-moved-in and moved-in paths."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_deposit_payment, seed_payment
from property_rental.billing import (
    PostgresRentBillingService,
    initial_billing_period,
    month_end,
    prorated_monthly_usd_cents,
)
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseSignCommand,
    PostgresLeaseService,
)
from property_rental.lease_termination import TerminationBasis, TerminationContext
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    MoveInOccupant,
    PostgresMoveInService,
    RecordLeaseMoveInCommand,
)
from property_rental.unpaid_initial_termination import (
    CreditMovedInInitialRentCommand,
    PostgresUnpaidInitialTerminationService,
    ResolveNeverMovedInCommand,
    UnpaidInitialTerminationAuthorizationError,
    UnpaidInitialTerminationInvalidError,
)
from test_billing_service_migration import authenticated, financial_database_url, initial_command
from test_invoice import mutation_headers
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_payment_api_migration import api
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)

PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
ALL = (
    "leases.terminate",
    "deposits.dispose",
    "invoices.void",
    "invoices.adjust",
    "property.manage",
)
SNAPSHOT_TABLES = ("leases", "reservations", "deposits", "invoices", "units")
# V1-058 migration 227 adds the Unit setup columns: NULL, or the Floor item linked from the
# Floor text; V1-061 migration 251 adds the default Rent (NULL). Every other value must
# stay as it was.
UNIT_SETUP_COLUMNS = (
    "ARRAY['floor_item_id','size_square_metres','bedrooms','bathrooms',"
    "'view_item_id','kitchen_item_id','notes',"
    "'default_monthly_rent_usd_cents']"
)


def row(url: str, query: str, *parameters: object) -> Any:
    with psycopg.connect(url) as connection:
        return connection.execute(query, parameters).fetchone()


def signed_with_initial(url: str, start_offset: int) -> dict[str, Any]:
    """Reserve, sign with the Reservation and issue the Initial Rent Invoice."""
    with psycopg.connect(url) as connection:
        actor_id, prop, unit, customer = setup_reservation_sources(connection)
        _, ids = create_reservation(
            connection,
            actor_id=actor_id,
            property_id=prop,
            unit_id=unit,
            customer_id=customer,
            expiration_days=10,
        )
        today = reservation_business_date(connection, prop)
    start = today - timedelta(days=start_offset)
    leases = PostgresLeaseService(runtime_database_url(), prop, actor_id)
    who = actor(actor_id, prop, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY)
    draft = draft_command(
        unit, customer, start_date=start, end_date=month_end(start + timedelta(days=365))
    )
    leases.draft(draft, actor=who)
    leases.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    leases.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=ids["reservation_id"],
        ),
        actor=who,
    )
    issued = PostgresRentBillingService(financial_database_url(), prop, actor_id).generate(
        initial_command(
            draft.lease_id,
            uuid4(),
            period_start=start,
            issued_at=datetime(start.year, start.month, start.day, tzinfo=PHNOM_PENH),
        ),
        actor=authenticated(actor_id, prop),
    )
    return {
        "actor": actor_id,
        "property": prop,
        "unit": unit,
        "customer": customer,
        "reservation": ids["reservation_id"],
        "deposit": ids["deposit_id"],
        "lease": draft.lease_id,
        "start": start,
        "today": today,
        "invoice": issued.invoice_id,
    }


def terminate(url: str, source: dict[str, Any]) -> UUID:
    """Terminate with the unpaid-Initial basis and signed clause reference; return the event."""
    event = uuid4()
    context = TerminationContext(
        basis=TerminationBasis.UNPAID_INITIAL_OBLIGATION,
        signed_lease_provision="Standard Lease clause 7.3: unpaid deposit or Initial Rent",
        approved_grounds="Initial Rent unpaid five days after the Lease Start Date",
        management_authorization_reference="Management decision UNPAID-001",
        evidence_reference="Invoice and deposit ledger review UNPAID-001",
        notice_required=False,
        notice_exception_reason="The signed clause allows termination without a notice period",
    )
    with psycopg.connect(url) as connection:
        current = connection.execute(
            "SELECT version,statement_timestamp() FROM app.leases WHERE id=%s", (source["lease"],)
        ).fetchone()
        assert current is not None
        connection.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                source["property"],
                uuid4(),
                "b" * 64,
                event,
                source["lease"],
                int(str(current[0])),
                source["today"],
                current[1],
                "BR-LEASE-005",
                "Customer did not pay the Initial obligation",
                source["actor"],
                Jsonb(context.intent()),
            ),
        )
    return event


def service(source: dict[str, Any]) -> PostgresUnpaidInitialTerminationService:
    return PostgresUnpaidInitialTerminationService(financial_database_url(), source["property"])


def rent_line(url: str, invoice: UUID) -> tuple[UUID, int]:
    found = row(
        url,
        "SELECT id,app.invoice_line_outstanding(id) FROM app.invoice_lines "
        "WHERE invoice_id=%s AND category='RENT'",
        invoice,
    )
    assert found is not None
    return UUID(str(found[0])), int(found[1])


def test_never_moved_in_with_nothing_paid_forfeits_voids_and_releases_the_unit(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    held = int(
        row(
            migrated_database_url,
            "SELECT app.deposit_held_value_at(%s,statement_timestamp())",
            source["deposit"],
        )[0]
    )
    event = terminate(migrated_database_url, source)
    command = ResolveNeverMovedInCommand(
        uuid4(), uuid4(), event, "VACANT", "Customer never moved in and did not pay"
    )
    who = actor(source["actor"], source["property"], *ALL)
    result = service(source).resolve_never_moved_in(command, actor=who)
    assert service(source).resolve_never_moved_in(command, actor=who) == result
    assert result["path"] == "NEVER_MOVED_IN"
    assert result["cause"] == "CUSTOMER_UNPAID_INITIAL_OBLIGATION"
    assert row(
        migrated_database_url, "SELECT status FROM app.invoices WHERE id=%s", source["invoice"]
    ) == ("VOID",)
    assert row(
        migrated_database_url, "SELECT status FROM app.units WHERE id=%s", source["unit"]
    ) == ("VACANT",)
    assert row(
        migrated_database_url,
        "SELECT status FROM app.reservations WHERE id=%s",
        source["reservation"],
    ) == ("COMPLETED",)
    disposition = row(
        migrated_database_url,
        "SELECT d.amount_usd_cents,c.governing_rule FROM app.deposit_dispositions d "
        "JOIN app.lease_deposit_disposition_contexts c ON c.disposition_id=d.id "
        "WHERE d.deposit_id=%s",
        source["deposit"],
    )
    # V1-056 slice 6 (owner answer to Q-2026-10-04-11): the resolution no longer forfeits;
    # the Security Deposit is forfeited only through a confirmed forfeiture draft.
    assert disposition is None
    assert row(
        migrated_database_url,
        "SELECT app.deposit_held_value_at(%s,statement_timestamp())",
        source["deposit"],
    ) == (held,)
    assert row(
        migrated_database_url,
        "SELECT cause,reason,actor_id FROM app.unpaid_initial_termination_resolutions WHERE id=%s",
        command.resolution_id,
    ) == (
        "CUSTOMER_UNPAID_INITIAL_OBLIGATION",
        "Customer never moved in and did not pay",
        source["actor"],
    )


def test_never_moved_in_partly_paid_keeps_the_payment_and_credits_the_remainder(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    line, outstanding = rent_line(migrated_database_url, source["invoice"])
    paid = min(1_000, outstanding - 1)
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=source["actor"],
            property_id=source["property"],
            customer_id=source["customer"],
            amount=paid,
        )
    allocation_service().post(
        source["property"],
        payment,
        allocation_designated(source["invoice"], line, paid),
        actor=allocation_actor(source["actor"], source["property"]),
    )
    event = terminate(migrated_database_url, source)
    cleaning = ResolveNeverMovedInCommand(
        uuid4(), uuid4(), event, "CLEANING", "Customer never moved in", "Parking needs cleaning"
    )
    with pytest.raises(UnpaidInitialTerminationAuthorizationError):
        service(source).resolve_never_moved_in(
            cleaning, actor=actor(source["actor"], source["property"], *ALL[:-1])
        )
    result = service(source).resolve_never_moved_in(
        cleaning, actor=actor(source["actor"], source["property"], *ALL)
    )
    assert result["invoice_void_event_id"] is None
    assert result["credit_usd_cents"] == outstanding - paid
    assert row(
        migrated_database_url,
        "SELECT status,app.invoice_application_status(id) FROM app.invoices WHERE id=%s",
        source["invoice"],
    ) == ("PAID", "PAID")
    assert row(
        migrated_database_url,
        "SELECT app.invoice_line_application_value_at(%s,'infinity')",
        line,
    ) == (paid,)
    assert row(
        migrated_database_url, "SELECT status FROM app.units WHERE id=%s", source["unit"]
    ) == ("CLEANING",)


def test_ground_is_verified_at_termination_time(migrated_database_url: str) -> None:
    too_early = signed_with_initial(migrated_database_url, 3)
    with pytest.raises(psycopg.Error) as early:
        terminate(migrated_database_url, too_early)
    assert early.value.sqlstate == "22023"
    paid = signed_with_initial(migrated_database_url, 10)
    line, outstanding = rent_line(migrated_database_url, paid["invoice"])
    with psycopg.connect(migrated_database_url) as connection:
        missing = connection.execute(
            "SELECT required_usd_cents-app.deposit_held_value_at(id,statement_timestamp()) "
            "FROM app.deposits WHERE id=%s",
            (paid["deposit"],),
        ).fetchone()
        assert missing is not None
        if int(missing[0]) > 0:
            connection.execute(
                "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                "occurred_at,actor_id) VALUES (%s,%s,%s,%s,clock_timestamp(),%s)",
                (
                    uuid4(),
                    paid["deposit"],
                    seed_deposit_payment(
                        connection,
                        deposit_id=paid["deposit"],
                        actor_id=paid["actor"],
                        amount=int(missing[0]),
                    ),
                    int(missing[0]),
                    paid["actor"],
                ),
            )
        payment = seed_payment(
            connection,
            actor_id=paid["actor"],
            property_id=paid["property"],
            customer_id=paid["customer"],
            amount=outstanding,
        )
    allocation_service().post(
        paid["property"],
        payment,
        allocation_designated(paid["invoice"], line, outstanding),
        actor=allocation_actor(paid["actor"], paid["property"]),
    )
    with pytest.raises(psycopg.Error) as nothing_unpaid:
        terminate(migrated_database_url, paid)
    assert nothing_unpaid.value.sqlstate == "22023"
    assert row(
        migrated_database_url, "SELECT status FROM app.leases WHERE id=%s", paid["lease"]
    ) == ("SIGNED",)


def expected_credit(monthly: int, start: date, termination: date) -> int:
    _, end, _ = initial_billing_period(start)
    credit = 0
    segment_start = start
    while segment_start <= end:
        segment_end = min(month_end(segment_start), end)
        amount = prorated_monthly_usd_cents(monthly, segment_start, segment_end)
        if segment_start > termination:
            credit += amount
        elif segment_end > termination:
            credit += amount - prorated_monthly_usd_cents(monthly, segment_start, termination)
        segment_start = segment_end + timedelta(days=1)
    return credit


def test_moved_in_termination_credits_rent_after_the_termination_date(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    version = int(
        row(migrated_database_url, "SELECT version FROM app.leases WHERE id=%s", source["lease"])[0]
    )
    move_in = PostgresMoveInService(runtime_database_url(), source["property"], source["actor"])
    move_in.record_lease_move_in(
        RecordLeaseMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=source["lease"],
            expected_lease_version=version,
            actual_move_in_date=source["today"],
            occupants=(MoveInOccupant(uuid4(), source["customer"]),),
            reason="Customer moved in",
            authorization_reference=MOVE_IN_CAPABILITY,
        ),
        actor=actor(source["actor"], source["property"], MOVE_IN_CAPABILITY),
    )
    event = terminate(migrated_database_url, source)
    who = actor(source["actor"], source["property"], *ALL)
    with pytest.raises(UnpaidInitialTerminationInvalidError):
        service(source).resolve_never_moved_in(
            ResolveNeverMovedInCommand(uuid4(), uuid4(), event, "VACANT", "Wrong path"),
            actor=who,
        )
    monthly = int(
        row(
            migrated_database_url,
            "SELECT monthly_rent_usd_cents FROM app.leases WHERE id=%s",
            source["lease"],
        )[0]
    )
    command = CreditMovedInInitialRentCommand(uuid4(), uuid4(), event, "Rent after termination")
    result = service(source).credit_moved_in_initial_rent(command, actor=who)
    assert result["path"] == "MOVED_IN"
    assert result["credit_usd_cents"] == expected_credit(monthly, source["start"], source["today"])
    assert service(source).credit_moved_in_initial_rent(command, actor=who) == result
    assert row(
        migrated_database_url, "SELECT status FROM app.invoices WHERE id=%s", source["invoice"]
    ) != ("VOID",)
    assert row(
        migrated_database_url, "SELECT status FROM app.units WHERE id=%s", source["unit"]
    ) == ("OCCUPIED",)


def snapshot(url: str) -> dict[str, Any]:
    with psycopg.connect(url) as connection:
        return {
            table: connection.execute(
                "SELECT COALESCE(jsonb_agg(to_jsonb(t)"
                f"{'-' + UNIT_SETUP_COLUMNS if table == 'units' else ''} "
                "ORDER BY t.id),'[]'::jsonb) "
                f"FROM app.{table} t"
            ).fetchone()
            for table in SNAPSHOT_TABLES
        }


def test_upgrade_to_unpaid_initial_termination_keeps_earlier_records(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("unpaid_initial_termination") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20261005_69")
        with psycopg.connect(temporary) as connection:
            actor_id, prop, unit, customer = setup_reservation_sources(connection)
            create_reservation(
                connection,
                actor_id=actor_id,
                property_id=prop,
                unit_id=unit,
                customer_id=customer,
                expiration_days=10,
            )
        before = snapshot(temporary)
        alembic_command.upgrade(config, "head")
        assert snapshot(temporary) == before


def test_unpaid_initial_termination_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261005_70")
    assert revision is not None and revision.down_revision == "20261005_69"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


CONTEXT_BODY = {
    "basis": "UNPAID_INITIAL_OBLIGATION",
    "signed_lease_provision": "Standard Lease clause 7.3: unpaid deposit or Initial Rent",
    "approved_grounds": "Initial Rent unpaid five days after the Lease Start Date",
    "management_authorization_reference": "Management decision UNPAID-002",
    "evidence_reference": "Invoice and deposit ledger review UNPAID-002",
    "notice_required": False,
    "notice_exception_reason": "The signed clause allows termination without a notice period",
}


def terminate_body(url: str, source: dict[str, Any], **changes: object) -> dict[str, object]:
    # Sub-slice 10i-1: the route sends no termination time; the database takes its own.
    del url
    body: dict[str, object] = {
        "event_id": str(uuid4()),
        "actual_termination_date": source["today"].isoformat(),
        "governing_event_reference": "BR-LEASE-005",
        "reason": "Customer did not pay the Initial obligation",
        "context": CONTEXT_BODY,
    }
    body.update(changes)
    return body


def test_terminate_route_accepts_the_unpaid_initial_basis_and_rejects_a_mismatched_reference(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    who = actor(source["actor"], source["property"], *ALL)
    path = f"/api/v1/leases/{source['lease']}/terminate"
    version = int(
        row(migrated_database_url, "SELECT version FROM app.leases WHERE id=%s", source["lease"])[0]
    )
    mismatch = api(who).post(
        path,
        json=terminate_body(
            migrated_database_url, source, governing_event_reference="BR-LEASE-021"
        ),
        headers=mutation_headers(version=version),
    )
    assert mismatch.status_code == 422, mismatch.text
    assert row(
        migrated_database_url, "SELECT status FROM app.leases WHERE id=%s", source["lease"]
    ) == ("SIGNED",)
    unknown = api(who).post(
        path,
        json=terminate_body(
            migrated_database_url, source, context={**CONTEXT_BODY, "invented": "field"}
        ),
        headers=mutation_headers(version=version),
    )
    assert unknown.status_code == 422
    key = uuid4()
    body = terminate_body(migrated_database_url, source)
    reply = api(who).post(path, json=body, headers=mutation_headers(key=key, version=version))
    assert reply.status_code == 200, reply.text
    assert reply.json()["data"]["status"] == "TERMINATED"
    context = row(
        migrated_database_url,
        "SELECT context_data->>'basis' FROM app.lease_termination_contexts "
        "WHERE command_event_id=%s",
        UUID(str(body["event_id"])),
    )
    assert context == ("UNPAID_INITIAL_OBLIGATION",)
    replay = api(who).post(path, json=body, headers=mutation_headers(key=key, version=version))
    assert replay.status_code == 200 and replay.json()["data"] == reply.json()["data"]


def resolution_path(source: dict[str, Any], event: UUID, kind: str) -> str:
    return (
        f"/api/v1/properties/{source['property']}/lease-terminations/{event}/unpaid-initial-{kind}"
    )


def test_never_moved_in_route_resolves_replays_and_needs_every_capability(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    event = terminate(migrated_database_url, source)
    path = resolution_path(source, event, "never-moved-in")
    body = {
        "resolution_id": str(uuid4()),
        "unit_status": "CLEANING",
        "unit_status_reason": "Parking needs cleaning",
        "reason": "Customer never moved in and did not pay",
    }
    weak = actor(source["actor"], source["property"], *ALL[:-1])
    assert api(weak).post(path, json=body, headers=mutation_headers()).status_code == 403
    missing_reason = {key: value for key, value in body.items() if key != "unit_status_reason"}
    full = actor(source["actor"], source["property"], *ALL)
    assert api(full).post(path, json=missing_reason, headers=mutation_headers()).status_code == 422
    assert row(
        migrated_database_url, "SELECT status FROM app.units WHERE id=%s", source["unit"]
    ) != ("CLEANING",)
    key = uuid4()
    reply = api(full).post(path, json=body, headers=mutation_headers(key=key))
    assert reply.status_code == 201, reply.text
    assert reply.headers["cache-control"] == "private, no-store"
    data = reply.json()["data"]
    assert (
        data["path"] == "NEVER_MOVED_IN" and data["cause"] == "CUSTOMER_UNPAID_INITIAL_OBLIGATION"
    )
    replay = api(full).post(path, json=body, headers=mutation_headers(key=key))
    assert replay.status_code == 201 and replay.json()["data"] == data
    assert row(
        migrated_database_url, "SELECT status FROM app.units WHERE id=%s", source["unit"]
    ) == ("CLEANING",)
    other = api(full).post(
        path, json={**body, "resolution_id": str(uuid4())}, headers=mutation_headers()
    )
    # A second resolution of the same termination is refused as invalid state, not replayed.
    assert other.status_code == 422
    unknown = api(full).post(
        resolution_path(source, uuid4(), "never-moved-in"),
        json={**body, "resolution_id": str(uuid4())},
        headers=mutation_headers(),
    )
    assert unknown.status_code == 404
    no_csrf = mutation_headers()
    no_csrf.pop("X-CSRF-Token")
    assert api(full).post(path, json=body, headers=no_csrf).status_code == 403


def test_moved_in_credit_route_credits_once_and_refuses_the_wrong_path(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    version = int(
        row(migrated_database_url, "SELECT version FROM app.leases WHERE id=%s", source["lease"])[0]
    )
    PostgresMoveInService(
        runtime_database_url(), source["property"], source["actor"]
    ).record_lease_move_in(
        RecordLeaseMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=source["lease"],
            expected_lease_version=version,
            actual_move_in_date=source["today"],
            occupants=(MoveInOccupant(uuid4(), source["customer"]),),
            reason="Customer moved in",
            authorization_reference=MOVE_IN_CAPABILITY,
        ),
        actor=actor(source["actor"], source["property"], MOVE_IN_CAPABILITY),
    )
    event = terminate(migrated_database_url, source)
    full = actor(source["actor"], source["property"], *ALL)
    wrong = api(full).post(
        resolution_path(source, event, "never-moved-in"),
        json={
            "resolution_id": str(uuid4()),
            "unit_status": "VACANT",
            "reason": "Wrong path",
        },
        headers=mutation_headers(),
    )
    assert wrong.status_code == 422
    path = resolution_path(source, event, "moved-in-credit")
    body = {"resolution_id": str(uuid4()), "reason": "Rent after termination"}
    assert (
        api(actor(source["actor"], source["property"], "leases.terminate"))
        .post(path, json=body, headers=mutation_headers())
        .status_code
        == 403
    )
    key = uuid4()
    reply = api(full).post(path, json=body, headers=mutation_headers(key=key))
    assert reply.status_code == 201, reply.text
    data = reply.json()["data"]
    monthly = int(
        row(
            migrated_database_url,
            "SELECT monthly_rent_usd_cents FROM app.leases WHERE id=%s",
            source["lease"],
        )[0]
    )
    assert data["path"] == "MOVED_IN"
    assert data["credit_usd_cents"] == expected_credit(monthly, source["start"], source["today"])
    replay = api(full).post(path, json=body, headers=mutation_headers(key=key))
    assert replay.status_code == 201 and replay.json()["data"] == data


def test_lease_timeline_lists_the_termination_and_the_explicit_follow_up_in_order(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    event = terminate(migrated_database_url, source)
    full = actor(source["actor"], source["property"], *ALL, "leases.read")
    resolution = uuid4()
    reply = api(full).post(
        resolution_path(source, event, "never-moved-in"),
        json={
            "resolution_id": str(resolution),
            "unit_status": "VACANT",
            "reason": "Customer never moved in and did not pay",
        },
        headers=mutation_headers(),
    )
    assert reply.status_code == 201, reply.text
    timeline = api(full).get(f"/api/v1/leases/{source['lease']}/timeline")
    assert timeline.status_code == 200, timeline.text
    items = timeline.json()["data"]
    kinds = [item["event_kind"] for item in items]
    assert kinds.index("lease.terminate") < kinds.index("lease.unpaid_initial_never_moved_in")
    follow_up = next(item for item in items if item["event_kind"].startswith("lease.unpaid_"))
    assert follow_up["event_id"] == str(resolution)
    assert follow_up["source_reference"] == str(event)
    assert follow_up["reason"] == "Customer never moved in and did not pay"
    assert follow_up["source_href"].endswith(f"#timeline-{resolution}")
    paged = api(full).get(f"/api/v1/leases/{source['lease']}/timeline", params={"limit": "1"})
    assert len(paged.json()["data"]) == 1 and paged.json()["page"]["next_cursor"] is not None


def test_lease_timeline_labels_the_moved_in_credit_separately(
    migrated_database_url: str,
) -> None:
    source = signed_with_initial(migrated_database_url, 10)
    version = int(
        row(migrated_database_url, "SELECT version FROM app.leases WHERE id=%s", source["lease"])[0]
    )
    PostgresMoveInService(
        runtime_database_url(), source["property"], source["actor"]
    ).record_lease_move_in(
        RecordLeaseMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=source["lease"],
            expected_lease_version=version,
            actual_move_in_date=source["today"],
            occupants=(MoveInOccupant(uuid4(), source["customer"]),),
            reason="Customer moved in",
            authorization_reference=MOVE_IN_CAPABILITY,
        ),
        actor=actor(source["actor"], source["property"], MOVE_IN_CAPABILITY),
    )
    event = terminate(migrated_database_url, source)
    full = actor(source["actor"], source["property"], *ALL, "leases.read")
    credit = api(full).post(
        resolution_path(source, event, "moved-in-credit"),
        json={"resolution_id": str(uuid4()), "reason": "Rent after termination"},
        headers=mutation_headers(),
    )
    assert credit.status_code == 201, credit.text
    timeline = api(full).get(f"/api/v1/leases/{source['lease']}/timeline")
    kinds = [item["event_kind"] for item in timeline.json()["data"]]
    assert "lease.unpaid_initial_moved_in_credit" in kinds
    assert "lease.unpaid_initial_never_moved_in" not in kinds
