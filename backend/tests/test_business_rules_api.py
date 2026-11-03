"""Business rules API (General Ledger phase 6 step 1; owner 31/10/2026 and 03/11/2026).

Reading needs `configuration.read` for the Property; a change or a new rule needs
`settings.manage` and the browser mutation checks. The database refusals map to 404, 409 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.business_rules_api import (
    BusinessRule,
    BusinessRuleConflict,
    BusinessRuleInvalid,
    BusinessRuleNotFound,
    BusinessRuleValue,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

TODAY = date(2026, 11, 3)
HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=rules-token",
    "X-CSRF-Token": "rules-token",
}


def _value(value: int, on: date, reason: str | None = None) -> BusinessRuleValue:
    return BusinessRuleValue(value, on, reason, datetime(2026, 1, 1, tzinfo=UTC), None)


@dataclass
class InMemoryRules:
    property_id: UUID = field(default_factory=uuid4)
    rules: dict[str, BusinessRule] = field(default_factory=dict)
    changes: list[tuple[str, int, date, str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rules["EXPENSE_LIMIT"] = BusinessRule(
            "EXPENSE_LIMIT",
            "Expense limit",
            "កម្រិតចំណាយ",
            "USD_CENTS",
            "LEDGER",
            True,
            (_value(10000, date(2026, 1, 1)),),
        )

    def today(self, property_id: UUID) -> date:
        if property_id != self.property_id:
            raise BusinessRuleNotFound
        return TODAY

    def list_rules(self) -> tuple[BusinessRule, ...]:
        return tuple(self.rules.values())

    def set_rule(
        self,
        property_id: UUID,
        code: str,
        *,
        value: int,
        effective_from: date,
        reason: str,
        actor_id: str,
    ) -> None:
        rule = self.rules.get(code)
        if rule is None:
            raise BusinessRuleNotFound
        if effective_from < TODAY:
            raise BusinessRuleInvalid("A business rule change starts today or later")
        if any(row.effective_from == effective_from for row in rule.history):
            raise BusinessRuleConflict("A change for this date already exists")
        self.changes.append((code, value, effective_from, reason, actor_id))
        self.rules[code] = BusinessRule(
            rule.code,
            rule.name_en,
            rule.name_kh,
            rule.value_unit,
            rule.area,
            rule.used_by_app,
            (*rule.history, _value(value, effective_from, reason)),
        )

    def add_rule(
        self,
        property_id: UUID,
        *,
        code: str,
        name_en: str,
        name_kh: str,
        value_unit: str,
        area: str,
        value: int,
        effective_from: date,
        reason: str | None,
        actor_id: str,
    ) -> None:
        if code in self.rules:
            raise BusinessRuleConflict("A rule with this code already exists")
        self.rules[code] = BusinessRule(
            code, name_en, name_kh, value_unit, area, False, (_value(value, effective_from),)
        )


def client(flow: InMemoryRules, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, business_rule_flow=flow))


def test_reading_the_rules_needs_configuration_read() -> None:
    flow = InMemoryRules()
    url = f"/api/v1/properties/{flow.property_id}/business-rules"
    assert client(flow).get(url).status_code == 403
    answer = client(flow, "configuration.read").get(url)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    [rule] = answer.json()["data"]
    assert rule["code"] == "EXPENSE_LIMIT" and rule["in_force"]["value"] == 10000
    assert rule["waiting"] is None and len(rule["history"]) == 1
    other = client(flow, "configuration.read").get(f"/api/v1/properties/{uuid4()}/business-rules")
    assert other.status_code == 403


def test_a_change_needs_settings_manage_and_waits_until_its_date() -> None:
    flow = InMemoryRules()
    url = f"/api/v1/properties/{flow.property_id}/business-rules/EXPENSE_LIMIT"
    body = {"value": 15000, "effective_from": "2026-12-01", "reason": "More work"}
    assert client(flow, "configuration.read").put(url, json=body, headers=HEADERS).status_code == (
        403
    )
    owner = client(flow, "settings.manage")
    assert owner.put(url, json=body).status_code == 403
    answer = owner.put(url, json=body, headers=HEADERS)
    assert answer.status_code == 200
    [rule] = answer.json()["data"]
    assert rule["in_force"]["value"] == 10000
    assert rule["waiting"] == {
        "value": 15000,
        "effective_from": "2026-12-01",
        "reason": "More work",
        "created_at": "2026-01-01T00:00:00+00:00",
        "created_by": None,
    }
    assert owner.put(url, json=body, headers=HEADERS).status_code == 409
    for bad in (
        {**body, "effective_from": "2026-11-02"},
        {**body, "reason": "  "},
        {**body, "value": -1},
        {**body, "value": "100"},
        {**body, "extra": 1},
    ):
        assert owner.put(url, json=bad, headers=HEADERS).status_code == 422, bad
    missing = f"/api/v1/properties/{flow.property_id}/business-rules/NO_RULE"
    assert owner.put(missing, json=body, headers=HEADERS).status_code == 404
    lower = f"/api/v1/properties/{flow.property_id}/business-rules/no_rule"
    assert owner.put(lower, json=body, headers=HEADERS).status_code == 404


def test_the_owner_adds_a_rule_that_is_not_used_yet() -> None:
    flow = InMemoryRules()
    url = f"/api/v1/properties/{flow.property_id}/business-rules"
    body = {
        "code": "WATER_CHECK_DAY",
        "name_en": "Water check day",
        "name_kh": "ថ្ងៃពិនិត្យទឹក",
        "value_unit": "DAY_OF_MONTH",
        "area": "OTHER",
        "value": 10,
        "effective_from": "2026-11-03",
    }
    owner = client(flow, "settings.manage")
    answer = owner.post(url, json=body, headers=HEADERS)
    assert answer.status_code == 201
    added = [rule for rule in answer.json()["data"] if rule["code"] == "WATER_CHECK_DAY"]
    assert added[0]["used_by_app"] is False and added[0]["in_force"]["value"] == 10
    assert owner.post(url, json=body, headers=HEADERS).status_code == 409
    for bad in ({**body, "code": "lower"}, {**body, "value_unit": "WEEKS"}, {**body, "area": "X"}):
        assert owner.post(url, json=bad, headers=HEADERS).status_code == 422, bad
