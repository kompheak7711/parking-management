"""Services and Service types in Settings: the routes (V1-058 R7b-6a; DL-075; SEC-019)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.service_settings_api import (
    LEASE_HOLDS_TWO_OF_TYPE,
    SERVICE_TYPE_HAS_SERVICES,
    UNIT_TYPE_NEEDS_CLEANING_RATE,
    CleaningRateChange,
    CleaningRateCreate,
    ServiceChange,
    ServiceCreate,
    ServiceSettingsConflict,
    ServiceSettingsIdReused,
    ServiceSettingsInvalid,
    ServiceSettingsNotFound,
    ServiceSettingsOutOfDate,
    ServiceSettingsUnavailable,
    ServiceTypeChange,
    ServiceTypeCreate,
    _refusal,
)
from test_invoice import actor, mutation_headers

PROPERTY = uuid4()


@dataclass
class Flow:
    calls: list[tuple[str, object]] = field(default_factory=list)
    error: Exception | None = None

    def _answer(self, name: str, value: object) -> dict[str, object]:
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error
        return {"id": name}

    def read(self, property_id: UUID, today: date) -> dict[str, object]:
        self._answer("read", (property_id, today))
        return {"services": [], "service_types": []}

    def add_service(
        self, property_id: UUID, actor_id: UUID, body: ServiceCreate
    ) -> dict[str, object]:
        return self._answer("add_service", body)

    def change_service(
        self, property_id: UUID, actor_id: UUID, service_id: UUID, body: ServiceChange
    ) -> dict[str, object]:
        return self._answer("change_service", (service_id, body))

    def add_type(
        self, property_id: UUID, actor_id: UUID, body: ServiceTypeCreate
    ) -> dict[str, object]:
        return self._answer("add_type", body)

    def change_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, body: ServiceTypeChange
    ) -> dict[str, object]:
        return self._answer("change_type", (type_id, body))

    def remove_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, version: int
    ) -> dict[str, object]:
        return self._answer("remove_type", (type_id, version))

    def read_cleaning(self, property_id: UUID) -> dict[str, object]:
        self._answer("read_cleaning", property_id)
        return {"cleaning_rates": [], "unit_types": []}

    def save_cleaning_rate(
        self,
        property_id: UUID,
        actor_id: UUID,
        rate_id: UUID,
        body: CleaningRateCreate | CleaningRateChange,
    ) -> dict[str, object]:
        return self._answer("save_cleaning_rate", (rate_id, body))

    def remove_cleaning_rate(
        self, property_id: UUID, actor_id: UUID, rate_id: UUID, version: int
    ) -> dict[str, object]:
        return self._answer("remove_cleaning_rate", (rate_id, version))


def client(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    api = TestClient(create_app(actor_resolver=lambda _: who, service_settings_flow=flow))
    api.cookies.set("__Host-prm_csrf", "csrf")
    return api


SERVICE = {
    "service_id": str(uuid4()),
    "name_en": "Trash Collection",
    "name_km": "ប្រមូលសំរាម",
    "service_type_id": None,
    "monthly_rate_usd_cents": 500,
    "starts_on": "2026-11-01",
}


def test_reading_needs_settings_access_configuration_read_or_lease_drafting() -> None:
    flow = Flow()
    url = f"/api/v1/properties/{PROPERTY}/service-settings"
    assert client(flow, None).get(url).status_code == 401
    assert client(flow, actor(PROPERTY, "units.read")).get(url).status_code == 403
    for capability, manage in (
        ("leases.draft", False),
        ("configuration.read", False),
        ("settings.manage", True),
    ):
        answer = client(flow, actor(PROPERTY, capability)).get(url)
        assert answer.status_code == 200
        assert answer.json()["data"]["can_manage"] is manage
        assert set(answer.json()["data"]) == {"services", "service_types", "today", "can_manage"}
    assert client(flow, actor(PROPERTY, "settings.manage")).get(f"{url}?x=1").status_code == 422
    flow.error = ServiceSettingsNotFound()
    assert client(flow, actor(PROPERTY, "settings.manage")).get(url).status_code == 404


def test_every_change_needs_settings_access_origin_and_csrf_and_strict_fields() -> None:
    flow = Flow()
    type_id = uuid4()
    changes = [
        (f"/api/v1/properties/{PROPERTY}/services", SERVICE, 201),
        (
            f"/api/v1/properties/{PROPERTY}/services/{uuid4()}",
            {"name_en": "Trash", "service_type_id": str(type_id), "version": 2},
            200,
        ),
        (
            f"/api/v1/properties/{PROPERTY}/service-types",
            {"service_type_id": str(type_id), "name_en": "Trash", "one_per_lease": True},
            201,
        ),
        (
            f"/api/v1/properties/{PROPERTY}/service-types/{type_id}",
            {"name_en": "Trash", "one_per_lease": False, "version": 1},
            200,
        ),
        (f"/api/v1/properties/{PROPERTY}/service-types/{type_id}/remove", {"version": 3}, 200),
    ]
    manager = client(flow, actor(PROPERTY, "configuration.read", "leases.draft"))
    owner = client(flow, actor(PROPERTY, "settings.manage"))
    for url, body, done in changes:
        assert manager.post(url, json=body, headers=mutation_headers()).status_code == 403
        assert owner.post(url, json=body).status_code == 403  # no Origin or CSRF
        assert (
            owner.post(
                url, json={**cast(dict[str, object], body), "extra": 1}, headers=mutation_headers()
            ).status_code
            == 422
        )
        assert owner.post(url, json=body, headers=mutation_headers()).status_code == done
    assert [name for name, _ in flow.calls] == [
        "add_service",
        "change_service",
        "add_type",
        "change_type",
        "remove_type",
    ]
    # A Service starts on the 1st of a month and has a rate above zero.
    for wrong in ({"starts_on": "2026-11-02"}, {"monthly_rate_usd_cents": 0}, {"name_en": ""}):
        assert (
            owner.post(
                changes[0][0], json={**SERVICE, **wrong}, headers=mutation_headers()
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (ServiceSettingsInvalid(), 422, None),
        (ServiceSettingsIdReused(), 409, "SETTINGS_ID_REUSED"),
        (ServiceSettingsOutOfDate(), 409, "SETTINGS_OUT_OF_DATE"),
        (ServiceSettingsConflict(LEASE_HOLDS_TWO_OF_TYPE), 409, "LEASE_HOLDS_TWO_OF_TYPE"),
        (ServiceSettingsConflict(SERVICE_TYPE_HAS_SERVICES), 409, "SERVICE_TYPE_HAS_SERVICES"),
        (
            ServiceSettingsConflict(UNIT_TYPE_NEEDS_CLEANING_RATE),
            409,
            "UNIT_TYPE_NEEDS_CLEANING_RATE",
        ),
        (ServiceSettingsNotFound(), 404, None),
        (ServiceSettingsUnavailable(), 503, None),
    ],
)
def test_refusals_answer_their_status(error: Exception, status: int, detail: str | None) -> None:
    flow = Flow(error=error)
    answer = client(flow, actor(PROPERTY, "settings.manage")).post(
        f"/api/v1/properties/{PROPERTY}/services", json=SERVICE, headers=mutation_headers()
    )
    assert answer.status_code == status
    if detail is not None:
        assert detail in answer.text


class _Refused(psycopg.Error):
    def __init__(self, code: str) -> None:
        self._code = code
        super().__init__("refused")

    @property
    def sqlstate(self) -> str | None:  # type: ignore[override]
        return self._code


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("P5V01", ServiceSettingsConflict(LEASE_HOLDS_TWO_OF_TYPE)),
        ("P5V02", ServiceSettingsConflict(SERVICE_TYPE_HAS_SERVICES)),
        ("P5V03", ServiceSettingsConflict(UNIT_TYPE_NEEDS_CLEANING_RATE)),
        ("55000", ServiceSettingsUnavailable()),
        ("23505", ServiceSettingsIdReused()),
        ("22023", ServiceSettingsInvalid()),
        ("P0002", ServiceSettingsNotFound()),
        ("40P01", ServiceSettingsOutOfDate()),
    ],
)
def test_database_refusals_map_by_their_own_code(code: str, expected: Exception) -> None:
    found = _refusal(_Refused(code))
    assert type(found) is type(expected)
    if isinstance(expected, ServiceSettingsConflict):
        assert isinstance(found, ServiceSettingsConflict)
        assert found.refusal is expected.refusal


RATE = {
    "cleaning_rate_id": str(uuid4()),
    "name_en": "Small rooms",
    "name_km": None,
    "rate_usd_cents": 1500,
    "unit_types": ["COVERED", "UNCOVERED"],
}


def test_cleaning_rates_are_read_by_settings_readers_and_changed_with_settings_access() -> None:
    flow = Flow()
    url = f"/api/v1/properties/{PROPERTY}/cleaning-settings"
    assert client(flow, None).get(url).status_code == 401
    assert client(flow, actor(PROPERTY, "units.read")).get(url).status_code == 403
    read = client(flow, actor(PROPERTY, "configuration.read")).get(url)
    assert read.status_code == 200
    assert read.json()["data"] == {"cleaning_rates": [], "unit_types": [], "can_manage": False}
    assert client(flow, actor(PROPERTY, "settings.manage")).get(f"{url}?x=1").status_code == 422

    rate_id = uuid4()
    changes = [
        (f"/api/v1/properties/{PROPERTY}/cleaning-rates", RATE, 201),
        (
            f"/api/v1/properties/{PROPERTY}/cleaning-rates/{rate_id}",
            {**{k: v for k, v in RATE.items() if k != "cleaning_rate_id"}, "version": 2},
            200,
        ),
        (f"/api/v1/properties/{PROPERTY}/cleaning-rates/{rate_id}/remove", {"version": 3}, 200),
    ]
    manager = client(flow, actor(PROPERTY, "configuration.read"))
    owner = client(flow, actor(PROPERTY, "settings.manage"))
    for change_url, body, done in changes:
        assert manager.post(change_url, json=body, headers=mutation_headers()).status_code == 403
        assert owner.post(change_url, json=body).status_code == 403  # no Origin or CSRF
        assert (
            owner.post(
                change_url,
                json={**cast(dict[str, object], body), "extra": 1},
                headers=mutation_headers(),
            ).status_code
            == 422
        )
        assert owner.post(change_url, json=body, headers=mutation_headers()).status_code == done
    calls = [value for name, value in flow.calls if name != "read_cleaning"]
    added, changed, removed = calls
    assert isinstance(added, tuple) and added[0] == UUID(str(RATE["cleaning_rate_id"]))
    assert isinstance(changed, tuple) and changed[0] == rate_id
    assert isinstance(changed[1], CleaningRateChange) and changed[1].version == 2
    assert removed == (rate_id, 3)
    # A rate is at least one cent; Unit Type codes are list codes.
    for wrong in ({"rate_usd_cents": 0}, {"unit_types": ["studio"]}, {"unit_types": None}):
        assert (
            owner.post(
                changes[0][0], json={**RATE, **wrong}, headers=mutation_headers()
            ).status_code
            == 422
        )
    flow.error = ServiceSettingsConflict(UNIT_TYPE_NEEDS_CLEANING_RATE)
    refused = owner.post(changes[2][0], json={"version": 3}, headers=mutation_headers())
    assert refused.status_code == 409 and "UNIT_TYPE_NEEDS_CLEANING_RATE" in refused.text
