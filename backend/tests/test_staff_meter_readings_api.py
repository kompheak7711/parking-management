"""Staff bot readings in Utilities (Telegram bots step 4c, DL-176, API-TG-006).

Reading and answering both need `utility_readings.record`; an answer needs the browser mutation
checks. The database refusals map to 403, 404 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import Json, ProductNotFound

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=meters-token",
    "X-CSRF-Token": "meters-token",
}


@dataclass
class InMemoryReadings:
    property_id: UUID = field(default_factory=uuid4)
    proposal_id: UUID = field(default_factory=uuid4)
    calls: list[tuple[list[UUID], str]] = field(default_factory=list)

    def waiting(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        return [
            {
                "run_id": str(uuid4()),
                "reading_date": "2026-11-24",
                "sent_by": "Son Sokhen",
                "readings": [{"proposal_id": str(self.proposal_id), "unit": "A101"}],
            }
        ]

    def decide(
        self, property_id: UUID, proposal_ids: list[UUID], decision: str, *, actor_id: str
    ) -> Json:
        if proposal_ids != [self.proposal_id]:
            raise ProductNotFound("a staff reading does not exist")
        self.calls.append((proposal_ids, decision))
        return {"decision": decision, "done": 1, "already": []}


def client(flow: InMemoryReadings, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, staff_meter_reading_flow=flow))


def test_staff_readings_need_the_right_to_record_readings() -> None:
    flow = InMemoryReadings()
    url = f"/api/v1/properties/{flow.property_id}/staff-meter-readings"
    body = {"proposal_ids": [str(flow.proposal_id)], "decision": "CONFIRMED"}
    assert client(flow, "utility.read").get(url).status_code == 403
    refused = client(flow, "utility.read").post(f"{url}/decisions", json=body, headers=HEADERS)
    assert refused.status_code == 403
    allowed = client(flow, "utility_readings.record")
    listed = allowed.get(url)
    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert listed.json()["data"][0]["readings"][0]["unit"] == "A101"
    answered = allowed.post(f"{url}/decisions", json=body, headers=HEADERS)
    assert answered.status_code == 200
    assert answered.json()["data"] == {"decision": "CONFIRMED", "done": 1, "already": []}
    assert flow.calls == [([flow.proposal_id], "CONFIRMED")]


def test_an_answer_is_checked() -> None:
    flow = InMemoryReadings()
    url = f"/api/v1/properties/{flow.property_id}/staff-meter-readings/decisions"
    allowed = client(flow, "utility_readings.record")
    good = {"proposal_ids": [str(flow.proposal_id)], "decision": "ASK_AGAIN"}
    # The browser mutation checks.
    assert allowed.post(url, json=good).status_code == 403
    for wrong in (
        good | {"decision": "MAYBE"},
        good | {"proposal_ids": []},
        good | {"proposal_ids": ["x"]},
        good | {"extra": 1},
    ):
        assert allowed.post(url, json=wrong, headers=HEADERS).status_code == 422, wrong
    unknown = good | {"proposal_ids": [str(uuid4())]}
    assert allowed.post(url, json=unknown, headers=HEADERS).status_code == 404
    assert flow.calls == []
