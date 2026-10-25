"""V1-057 `GET /api/v1/properties/{id}/home` (API-076; DL-072 answers 5, 7-9; DL-079 answer 9).

The application passes the Home sections the person may read; a person with none gets 403; the
dated items get their to-do group from the Property's day.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reports import ReportUnavailableError
from property_rental.settings import Settings

PROPERTY = uuid.uuid4()
PATH = f"/api/v1/properties/{PROPERTY}/home"


def actor(*capabilities: str, property_id: uuid.UUID = PROPERTY) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid.uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability, frozenset({str(property_id)}))
            for capability in capabilities
        ),
    )


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID, tuple[str, ...]]] = []
        self.fail = fail

    def home_page(
        self, actor_id: uuid.UUID, property_id: uuid.UUID, sections: Sequence[str]
    ) -> dict[str, object]:
        if self.fail:
            raise ReportUnavailableError("down")
        self.calls.append((actor_id, property_id, tuple(sections)))
        return {
            "as_of": "2026-10-25T03:30:00+00:00",
            "business_date": "2026-10-25",
            "timezone": "Asia/Phnom_Penh",
            "cards": {"lease_renewal": {"count": 2, "end_on_or_before": "2026-12-24"}},
            "todo": [
                {"kind": "overdue_initial_rent", "date": "2026-10-20"},
                {"kind": "reservation_expiring", "date": "2026-10-25"},
                {"kind": "lease_ending", "date": "2026-10-31"},
                {"kind": "lease_ending", "date": "2026-11-30"},
                {"kind": "draft_waiting", "date": "2026-10-20"},
            ],
        }

    def rows(
        self,
        read: str,
        actor_id: uuid.UUID,
        property_id: uuid.UUID,
        extra: Sequence[object] = (),
    ) -> list[dict[str, object]]:
        raise AssertionError("not used")

    def units(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        raise AssertionError("not used")

    def utility_rates(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        raise AssertionError("not used")


def client(person: AuthenticatedActor | None, store: FakeStore) -> TestClient:
    return TestClient(
        create_app(Settings(database_url=None), actor_resolver=lambda _: person, report_store=store)
    )


def test_the_home_page_needs_a_signed_in_person_with_a_read_right() -> None:
    store = FakeStore()
    assert client(None, store).get(PATH).status_code == 401
    assert client(actor("identity.read_self"), store).get(PATH).status_code == 403
    other_property = actor("leases.read", property_id=uuid.uuid4())
    assert client(other_property, store).get(PATH).status_code == 403
    assert store.calls == []


def test_the_home_page_passes_only_the_sections_the_person_may_read() -> None:
    store = FakeStore()
    staff = actor("units.read", "invoices.read", "leases.read", "reservations.dispose.wrong")
    answer = client(staff, store).get(PATH)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert store.calls[0][1:] == (PROPERTY, ("units", "invoices", "leases"))
    data = answer.json()["data"]
    assert data["sections"] == ["units", "invoices", "leases"]
    groups = ["overdue", "today", "this_week", "later", "today"]
    assert [item["group"] for item in data["todo"]] == groups
    assert data["todo_counts"] == {"overdue": 1, "today": 2, "this_week": 1, "later": 1}
    manager = actor("financial.approve")
    client(manager, store).get(PATH)
    assert store.calls[1][2] == ("approvals", "deposit_decisions", "settlements")


def test_the_home_page_refuses_query_text_and_reports_a_store_failure() -> None:
    person = actor("units.read")
    assert client(person, FakeStore()).get(f"{PATH}?units=all").status_code == 422
    assert client(person, FakeStore(fail=True)).get(PATH).status_code == 503
