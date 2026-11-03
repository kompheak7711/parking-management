"""Settings > Business API: document numbering and Invoice types (V1.1 part 2, DL-118).

Reading needs `configuration.read` for the Property; a change needs `settings.manage` and the
browser mutation checks. The database refusals map to 404, 409 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.business_settings_api import (
    BusinessSettingConflict,
    BusinessSettingNotFound,
    InvoiceType,
    NumberRule,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

WHEN = datetime(2026, 11, 3, tzinfo=UTC)
HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=settings-token",
    "X-CSRF-Token": "settings-token",
}


@dataclass
class InMemorySettings:
    property_id: UUID = field(default_factory=uuid4)
    rules: dict[str, NumberRule] = field(default_factory=dict)
    kinds: dict[str, InvoiceType] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rules = {
            "INVOICE": NumberRule("INVOICE", 2026, 124, "INVyy000n", WHEN, None),
            "RECEIPT": NumberRule("RECEIPT", 2026, 0, "RCPyy000n", WHEN, None),
        }
        self.kinds = {
            "FIRST_RENT": InvoiceType("FIRST_RENT", "First Rent", "ថ្លៃឈ្នួលដំបូង", True, 1, WHEN, None),
            "RENT": InvoiceType("RENT", "Monthly Rent", "ថ្លៃឈ្នួលប្រចាំខែ", True, 1, WHEN, None),
        }

    def _check(self, property_id: UUID) -> None:
        if property_id != self.property_id:
            raise BusinessSettingNotFound

    def number_rules(self, property_id: UUID) -> tuple[NumberRule, ...]:
        self._check(property_id)
        return tuple(self.rules.values())

    def set_letters(
        self, property_id: UUID, document_type: str, *, letters: str, actor_id: str
    ) -> None:
        self._check(property_id)
        rule = self.rules.get(document_type)
        if rule is None:
            raise BusinessSettingNotFound
        if any(
            other.letters == letters for key, other in self.rules.items() if key != document_type
        ):
            raise BusinessSettingConflict("Another document uses these letters")
        self.rules[document_type] = replace(rule, format=letters + "yy000n")

    def invoice_types(self) -> tuple[InvoiceType, ...]:
        return tuple(self.kinds.values())

    def set_late_payment(
        self, property_id: UUID, code: str, *, late_payment: bool, reason: str, actor_id: str
    ) -> None:
        self._check(property_id)
        kind = self.kinds.get(code)
        if kind is None:
            raise BusinessSettingNotFound
        self.reasons.append(reason)
        self.kinds[code] = replace(kind, late_payment=late_payment, version=kind.version + 1)


def client(flow: InMemorySettings, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, business_settings_flow=flow))


def test_reading_the_numbers_needs_configuration_read_and_shows_the_next_number() -> None:
    flow = InMemorySettings()
    url = f"/api/v1/properties/{flow.property_id}/number-rules"
    assert client(flow).get(url).status_code == 403
    answer = client(flow, "configuration.read").get(url)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    invoice, receipt = answer.json()["data"]
    assert (invoice["letters"], invoice["next_number"]) == ("INV", "INV260125")
    assert (receipt["format"], receipt["next_number"]) == ("RCPyy000n", "RCP260001")


def test_new_letters_need_settings_manage_and_must_be_unique() -> None:
    flow = InMemorySettings()
    url = f"/api/v1/properties/{flow.property_id}/number-rules/RECEIPT"
    reader = client(flow, "configuration.read")
    assert reader.put(url, json={"letters": "RC"}, headers=HEADERS).status_code == 403
    manager = client(flow, "configuration.read", "settings.manage")
    assert manager.put(url, json={"letters": "RC"}).status_code == 403
    assert manager.put(url, json={"letters": "rc"}, headers=HEADERS).status_code == 422
    assert manager.put(url, json={"letters": "INV"}, headers=HEADERS).status_code == 409
    changed = manager.put(url, json={"letters": "RC"}, headers=HEADERS)
    assert changed.status_code == 200
    assert changed.json()["data"][1]["next_number"] == "RC260001"
    missing = f"/api/v1/properties/{flow.property_id}/number-rules/NOTHING"
    assert manager.put(missing, json={"letters": "NO"}, headers=HEADERS).status_code == 404


def test_late_payment_for_a_type_needs_a_reason() -> None:
    flow = InMemorySettings()
    base = f"/api/v1/properties/{flow.property_id}/invoice-types"
    reader = client(flow, "configuration.read")
    [first, rent] = reader.get(base).json()["data"]
    assert first["code"] == "FIRST_RENT" and first["late_payment"] is True
    assert rent["name_kh"] == "ថ្លៃឈ្នួលប្រចាំខែ"
    manager = client(flow, "configuration.read", "settings.manage")
    url = base + "/FIRST_RENT"
    assert manager.put(url, json={"late_payment": False}, headers=HEADERS).status_code == 422
    assert (
        manager.put(url, json={"late_payment": False, "reason": " "}, headers=HEADERS).status_code
        == 422
    )
    changed = manager.put(url, json={"late_payment": False, "reason": "Owner"}, headers=HEADERS)
    assert changed.status_code == 200
    assert changed.json()["data"][0]["late_payment"] is False
    assert flow.reasons == ["Owner"]


def test_without_a_database_the_settings_are_unavailable() -> None:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {CapabilityGrant(capability="configuration.read", property_ids=frozenset({"*"}))}
        ),
    )
    answer = TestClient(create_app(actor_resolver=lambda _: who)).get(
        f"/api/v1/properties/{uuid4()}/invoice-types"
    )
    assert answer.status_code in {403, 503}
