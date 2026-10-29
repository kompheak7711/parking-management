"""Move-out cleaning charge and hand-back month routes on real PostgreSQL (V1-056 slice 11a)."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.identity import AuthenticatedActor
from test_hand_back_rent_migration import (
    AUGUST,
    hand_back,
    hand_back_database,  # noqa: F401
    lease_with_invoices,
    status,
    version,
)
from test_hand_back_rent_migration import staff as hand_back_staff
from test_invoice import mutation_headers
from test_payment_api_migration import api
from test_unit_cleaning_charge_migration import (
    cleaning_rows,
    migrated_database_url,  # noqa: F401
    moved_out_lease,
    staff,
)


def headers(who: AuthenticatedActor, *, version: int | None = None) -> dict[str, str]:
    return {**mutation_headers(version=version), "X-Billing-Actor-ID": who.actor_id}


def test_the_cleaning_rate_and_charge_routes_record_one_charge_from_the_rate_shown(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, unit = moved_out_lease(migrated_database_url)
    who = staff(human, prop, "invoices.create", "property.manage")
    client: TestClient = api(who)
    rate_url = f"/api/v1/properties/{prop}/units/{unit}/cleaning-rate"
    assert client.get(rate_url).json()["data"]["rate"] is None
    charge_url = f"/api/v1/properties/{prop}/leases/{lease}/cleaning-charge"
    unset = client.post(
        charge_url,
        json={"charge_id": str(uuid4()), "expected_rate_id": str(uuid4())},
        headers=headers(who),
    )
    assert unset.status_code == 409
    assert unset.json()["error"]["code"] == "CLEANING_RATE_NOT_SET"

    first = client.post(
        f"/api/v1/properties/{prop}/units/{unit}/cleaning-rates",
        json={
            "rate_id": str(uuid4()),
            "expected_current_rate_id": None,
            "rate_usd_cents": 2_500,
            "reason": "Move-out cleaning price",
        },
        headers=headers(who),
    )
    assert first.status_code == 201, first.text
    current = client.get(rate_url).json()["data"]["rate"]
    assert current["id"] == first.json()["data"]["id"]
    assert current["rate_usd_cents"] == 2_500
    # A form that still shows no rate is told the rate changed.
    stale = client.post(
        f"/api/v1/properties/{prop}/units/{unit}/cleaning-rates",
        json={
            "rate_id": str(uuid4()),
            "expected_current_rate_id": None,
            "rate_usd_cents": 3_000,
            "reason": "Move-out cleaning price",
        },
        headers=headers(who),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CLEANING_RATE_CHANGED"

    charge = uuid4()
    body = {"charge_id": str(charge), "expected_rate_id": str(current["id"])}
    recorded = client.post(charge_url, json=body, headers=headers(who))
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["data"]["rate_usd_cents"] == 2_500
    # The same charge id answers the same charge again; a second charge is refused.
    replayed = client.post(charge_url, json=body, headers=headers(who))
    assert replayed.status_code == 201
    assert replayed.json()["data"] == recorded.json()["data"]
    assert cleaning_rows(migrated_database_url, lease) == (1, 1)
    again = client.post(
        charge_url,
        json={"charge_id": str(uuid4()), "expected_rate_id": str(current["id"])},
        headers=headers(who),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "CLEANING_CHARGE_ALREADY_RECORDED"
    assert cleaning_rows(migrated_database_url, lease) == (1, 1)


def test_the_hand_back_routes_assess_and_void_an_unpaid_invoice_once(
    hand_back_database: str,  # noqa: F811
) -> None:
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august: UUID = scenario.invoices[AUGUST]
    hand_back(url, scenario, date(2026, 8, 3))
    who = hand_back_staff(scenario.human, scenario.prop)
    client = api(who)
    assessment = client.get(f"/api/v1/invoices/{august}/hand-back-assessment")
    assert assessment.status_code == 200, assessment.text
    data = assessment.json()["data"]
    assert (data["coverage"], data["action"]) == ("HAND_BACK_MONTH", "VOID")
    assert "lease_id" not in data and "hand_back_date" not in data
    body = {
        "action": "VOID",
        "expected_outstanding_usd_cents": data["outstanding_usd_cents"],
        "reason": "Customer handed back the Parking on 3 August",
    }
    key, first_version = uuid4(), version(url, august)
    first = {**headers(who, version=first_version), "Idempotency-Key": str(key)}
    resolved = client.post(
        f"/api/v1/invoices/{august}/hand-back-resolution", json=body, headers=first
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.headers["etag"] == f'"{version(url, august)}"'
    assert status(url, august) == "VOID"
    # The same key and version answer the stored result again.
    replayed = client.post(
        f"/api/v1/invoices/{august}/hand-back-resolution", json=body, headers=first
    )
    assert replayed.status_code == 200
    assert replayed.json()["data"] == resolved.json()["data"]
    assert replayed.headers["etag"] == resolved.headers["etag"]
    again = client.post(
        f"/api/v1/invoices/{august}/hand-back-resolution",
        json=body,
        headers=headers(who, version=version(url, august)),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "HAND_BACK_ALREADY_RESOLVED"
    reader = api(hand_back_staff(scenario.human, scenario.prop, "invoices.read"))
    assert reader.get(f"/api/v1/invoices/{august}/hand-back-assessment").status_code == 404
