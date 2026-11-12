"""Owner report of 12 Nov 2026 (DL-223, migration 20270719_374): a Lease draft is not saved over
a short-stay booking, and Sign Lease says why it stops.

The owner made a paid short-stay booking for 13 to 15 Nov 2026 on U301, then a Lease draft for
the same Unit from 11 Nov 2026. The draft was saved; "Receive and sign" stopped with a general
message that did not name the booking. The owner's rule C of 3 Nov 2026 (the booking wins: offer
another Unit or a later Start Date) is now applied when the draft is saved, and both steps name
the reason.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from property_rental.api_refusals import RefusedRequest
from property_rental.app import create_app
from property_rental.billing import month_end
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_api import PostgresLeaseResourceFlow
from test_lease_api_migration import headers
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    run,
    short_stay_database,
)
from test_short_stay_cancel_migration import CANCEL, WHY
from test_short_stay_check_in_migration import guest_with_id, read
from test_short_stay_lease_migration import draft, initial, sign

REVISION = "20270719_374"
RENT = 80_000


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_v12_lease_draft_booking") as database:
        yield database


def client(db: BookingDatabase) -> TestClient:
    scope = frozenset({str(db.property_id)})
    actor = AuthenticatedActor(
        actor_id=str(db.manager),
        capability_grants=frozenset(
            CapabilityGrant(value, scope) for value in ("leases.read", "leases.draft")
        ),
    )
    value = TestClient(
        create_app(
            actor_resolver=lambda _: actor,
            lease_resource_flow=PostgresLeaseResourceFlow(db.runtime_url),
        )
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def book(db: BookingDatabase, unit: uuid.UUID, start: int, nights: int) -> Any:
    """A guest books the Unit: check-in ``start`` days from today, for ``nights`` nights."""
    guest = guest_with_id(db)
    return run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, start, nights, customer_id=str(guest)),
        db.staff,
    )


def new_lease(db: BookingDatabase, unit: uuid.UUID, start: date) -> dict[str, object]:
    tenant = guest_with_id(db)
    return {
        "lease_id": str(uuid.uuid4()),
        "unit_id": str(unit),
        "primary_tenant_id": str(tenant),
        "primary_signer_id": str(uuid.uuid4()),
        "start_date": str(start),
        "end_date": str(month_end(start + timedelta(days=400))),
        "monthly_rent_usd_cents": RENT,
        "predecessor_lease_id": None,
        "additional_signers": [],
        "planned_occupant_customer_ids": [str(tenant)],
        "service_terms": [],
        "pet_term": None,
        "security_deposit_id": None,
        "event_id": str(uuid.uuid4()),
        "reason": "Lease draft for the Unit",
    }


def leases_of(db: BookingDatabase, unit: uuid.UUID) -> list[tuple[object, ...]]:
    with psycopg.connect(db.owner_url) as connection:
        return connection.execute(
            "SELECT id::text, status, start_date FROM app.leases WHERE unit_id = %s "
            "ORDER BY created_at",
            (unit,),
        ).fetchall()


def lease_state(db: BookingDatabase, lease: object) -> tuple[object, ...] | None:
    with psycopg.connect(db.owner_url) as connection:
        return connection.execute(
            "SELECT status, start_date FROM app.leases WHERE id = %s", (str(lease),)
        ).fetchone()


def test_migration_374_follows_the_head_of_main_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270716_391"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_lease_draft_over_a_booked_night_is_not_saved(stay_database: BookingDatabase) -> None:
    """The owner's case: the guest arrives in two days, the Lease would start today."""
    db = stay_database
    unit = db.studio
    book(db, unit, 2, 2)
    url = f"/api/v1/properties/{db.property_id}/leases"
    api = client(db)

    over = api.post(url, json=new_lease(db, unit, db.today), headers=headers())
    assert over.status_code == 409, over.text
    error = over.json()["error"]
    assert error["code"] == "LEASE_UNIT_BOOKED"
    assert "short-stay guest has booked this Unit" in error["message"]
    # DL-224: the words also name the third way out.
    assert "move the guest to another Unit first" in error["message"]
    assert leases_of(db, unit) == []

    # The check-out day is free: the Lease may start on it. Another Unit is free on every day.
    after = api.post(url, json=new_lease(db, unit, db.today + timedelta(days=4)), headers=headers())
    assert after.status_code == 201, after.text
    elsewhere = api.post(url, json=new_lease(db, db.one_bedroom, db.today), headers=headers())
    assert elsewhere.status_code == 201, elsewhere.text


def test_edit_draft_does_not_move_a_lease_onto_booked_nights(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    unit = db.two_bedroom
    book(db, unit, 5, 3)
    free_from = db.today + timedelta(days=8)
    api = client(db)
    made = api.post(
        f"/api/v1/properties/{db.property_id}/leases",
        json=new_lease(db, unit, free_from),
        headers=headers(),
    )
    assert made.status_code == 201, made.text
    lease = made.json()["data"]
    url = f"/api/v1/leases/{lease['lease_id']}"

    earlier = api.patch(
        url,
        json={
            "event_id": str(uuid.uuid4()),
            "start_date": str(db.today + timedelta(days=6)),
            "reason": "The Customer asked to start earlier",
        },
        headers=headers(lease["version"]),
    )
    assert earlier.status_code == 409, earlier.text
    assert earlier.json()["error"]["code"] == "LEASE_UNIT_BOOKED"
    assert lease_state(db, lease["lease_id"]) == ("DRAFTED", free_from)

    # A change that keeps the Lease off the booked nights is saved as before.
    rent = api.patch(
        url,
        json={
            "event_id": str(uuid.uuid4()),
            "monthly_rent_usd_cents": RENT + 1_000,
            "reason": "Rent agreed with the Customer",
        },
        headers=headers(lease["version"]),
    )
    assert rent.status_code == 200, rent.text


def test_a_booking_made_after_the_draft_wins_and_signing_says_why(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    unit = db.one_bedroom
    tenant = guest_with_id(db)
    lease = draft(db, tenant, unit)
    # The draft holds no day: a guest may still book the Unit, and the booking wins.
    made = book(db, unit, 2, 2)
    assert read(db, made)["status"] == "BOOKED"

    total = initial(db, lease)["total_usd_cents"] + 40_000
    with pytest.raises(RefusedRequest) as caught:
        sign(db, lease, total)
    refusal = caught.value.refusal
    assert (refusal.status_code, refusal.code) == (409, "SIGNING_UNIT_BOOKED")
    assert "short-stay guest has booked this Unit" in refusal.message
    assert "move the guest to another Unit first" in refusal.message
    assert lease_state(db, lease) == ("DRAFTED", db.today)
    with psycopg.connect(db.owner_url) as connection:
        paid = connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id = %s", (tenant,)
        ).fetchone()
    assert paid == (0,)

    # The draft that can no longer be signed is still cancelled the usual way.
    api = client(db)
    version = api.get(f"/api/v1/leases/{lease}").json()["data"]["version"]
    cancelled = api.post(
        f"/api/v1/leases/{lease}/cancel",
        json={"event_id": str(uuid.uuid4()), "reason": "A guest booked the Unit"},
        headers=headers(version),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert lease_state(db, lease) == ("CANCELLED", db.today)


def test_a_cancelled_booking_frees_its_nights_for_a_lease_draft(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    unit = db.studio
    made = book(db, unit, 20, 2)
    start = db.today + timedelta(days=19)
    url = f"/api/v1/properties/{db.property_id}/leases"
    api = client(db)
    # The studio holds the draft of the first test from day 4; that draft is not signed and so
    # holds no day against this one. Only the guest's booking stops it.
    stopped = api.post(url, json=new_lease(db, unit, start), headers=headers())
    assert stopped.status_code == 409, stopped.text
    assert stopped.json()["error"]["code"] == "LEASE_UNIT_BOOKED"
    run(db.runtime_url, CANCEL, db.property_id, made, WHY, read(db, made)["version"], db.staff)
    saved = api.post(url, json=new_lease(db, unit, start), headers=headers())
    assert saved.status_code == 201, saved.text
