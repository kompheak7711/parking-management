"""Real PostgreSQL HTTP record, replay and read of termination notices (V1-058 R3)."""

from __future__ import annotations

from uuid import uuid4

import psycopg

from property_rental.lease_notices import RecordLeaseNotice
from test_invoice import mutation_headers
from test_lease_notices_migration import source, staff
from test_payment_api_migration import api
from test_reservation_migration import migrated_database_url  # noqa: F401


def body(request: RecordLeaseNotice) -> dict[str, object]:
    return {
        "notice_id": str(request.notice_id),
        "expected_lease_version": request.expected_lease_version,
        "notice_date": request.notice_date.isoformat(),
        "intended_termination_date": (
            None
            if request.intended_termination_date is None
            else request.intended_termination_date.isoformat()
        ),
        "notice_text": request.notice_text,
        "governing_lease_provision": request.governing_lease_provision,
        "approved_grounds": request.approved_grounds,
        "notice_period_terms": request.notice_period_terms,
        "evidence_reference": request.evidence_reference,
        "communication_record": request.communication_record,
        "authorization_reference": request.authorization_reference,
        "reason": request.reason,
    }


def test_http_notice_is_recorded_once_read_back_and_leaves_the_lease_version(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    client = api(staff(human, prop))
    target = f"/api/v1/properties/{prop}/leases/{lease}/termination-notices"
    key = uuid4()
    first = client.post(target, json=body(request), headers=mutation_headers(key=key))
    assert first.status_code == 201, first.text
    saved = first.json()["data"]
    assert saved["id"] == str(request.notice_id)
    # The same key and body give the saved answer; a changed body with that key is refused.
    replay = client.post(target, json=body(request), headers=mutation_headers(key=key))
    assert replay.status_code == 201
    assert replay.json()["data"] == saved
    changed = {**body(request), "reason": "Another reason"}
    assert client.post(target, json=changed, headers=mutation_headers(key=key)).status_code == 409

    page = client.get(f"{target}?limit=10")
    assert page.status_code == 200, page.text
    assert [item["id"] for item in page.json()["data"]["items"]] == [str(request.notice_id)]
    # A notice is evidence only: the Lease keeps its version, so a later termination
    # can still name it with the version the person saw.
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute("SELECT version FROM app.leases WHERE id=%s", (lease,)).fetchone()
    assert row is not None and row[0] == request.expected_lease_version
    # Another Property's address hides the Lease.
    other = f"/api/v1/properties/{uuid4()}/leases/{lease}/termination-notices"
    assert client.get(other).status_code in {403, 404}
