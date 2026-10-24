"""Contract tests for authorized effective-dated configuration APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.configuration_api import (
    ConfigurationIdempotencyConflict,
    ConfigurationNotFound,
    ConfigurationPage,
    ConfiguredServiceRecord,
    ExchangeRateProvider,
    ExchangeRateQuote,
    ExchangeRateRecord,
    ExchangeRateSourceUnavailable,
    PostgresConfigurationFlow,
    ServiceRateRecord,
    UtilityRateRecord,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


@dataclass(slots=True)
class InMemoryConfigurationFlow:
    property_id: UUID
    service_id: UUID = field(default_factory=uuid4)
    service_rates: list[ServiceRateRecord] = field(default_factory=list)
    utility_rates: list[UtilityRateRecord] = field(default_factory=list)
    exchange_rates: list[ExchangeRateRecord] = field(default_factory=list)
    commands: dict[UUID, tuple[str, str, object]] = field(default_factory=dict)

    def _replay(self, key: UUID, action: str, digest: str) -> object | None:
        prior = self.commands.get(key)
        if prior is None:
            return None
        if prior[0] != action or prior[1] != digest:
            raise ConfigurationIdempotencyConflict
        return prior[2]

    def list_configured_services(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ConfiguredServiceRecord]:
        if property_id != self.property_id:
            raise ConfigurationNotFound
        records = (
            ConfiguredServiceRecord(
                self.service_id,
                self.property_id,
                "TRASH_COLLECTION",
                "Trash Collection",
            ),
            ConfiguredServiceRecord(
                UUID(int=self.service_id.int ^ 1),
                self.property_id,
                "WIFI",
                "Wi-Fi",
            ),
        )
        if cursor is None:
            visible = records[:limit]
            next_cursor = "configured-next" if limit < len(records) else None
            return ConfigurationPage(visible, next_cursor)
        if cursor != "configured-next":
            raise ValueError("Invalid cursor")
        return ConfigurationPage(records[1 : 1 + limit], None)

    def list_service_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ServiceRateRecord]:
        del cursor
        if property_id != self.property_id:
            raise ConfigurationNotFound
        return ConfigurationPage(tuple(self.service_rates[:limit]), None)

    def get_service_rate(self, rate_id: UUID) -> ServiceRateRecord:
        for rate in self.service_rates:
            if rate.id == rate_id:
                return rate
        raise ConfigurationNotFound

    def create_service_rate(self, property_id: UUID, **values: object) -> ServiceRateRecord:
        key = cast(UUID, values["idempotency_key"])
        replay = self._replay(key, "service", str(values["request_digest"]))
        if replay is not None:
            return replay  # type: ignore[return-value]
        if property_id != self.property_id or values["property_service_id"] != self.service_id:
            raise ConfigurationNotFound
        record = ServiceRateRecord(
            cast(UUID, values["rate_id"]),
            property_id,
            self.service_id,
            "TRASH_COLLECTION",
            "Trash Collection",
            cast(int, values["monthly_rate_usd_cents"]),
            cast(date, values["effective_date"]),
            cast(str | None, values["source_memo"]),
            datetime(2026, 8, 25, tzinfo=UTC),
        )
        self.service_rates.insert(0, record)
        self.commands[key] = (
            "service",
            str(values["request_digest"]),
            record,
        )
        return record

    def list_utility_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[UtilityRateRecord]:
        del cursor
        if property_id != self.property_id:
            raise ConfigurationNotFound
        return ConfigurationPage(tuple(self.utility_rates[:limit]), None)

    def get_utility_rate(self, rate_id: UUID) -> UtilityRateRecord:
        for rate in self.utility_rates:
            if rate.id == rate_id:
                return rate
        raise ConfigurationNotFound

    def create_utility_rate(self, property_id: UUID, **values: object) -> UtilityRateRecord:
        key = cast(UUID, values["idempotency_key"])
        replay = self._replay(key, "utility", str(values["request_digest"]))
        if replay is not None:
            return replay  # type: ignore[return-value]
        if property_id != self.property_id:
            raise ConfigurationNotFound
        record = UtilityRateRecord(
            cast(UUID, values["rate_id"]),
            property_id,
            str(values["utility_type"]),
            str(values["measurement_unit_code"]),
            cast(Decimal, values["rate_usd_per_unit"]),
            cast(date, values["effective_date"]),
            cast(datetime, values["notice_at"]),
            str(values["notice_evidence"]),
            cast(str | None, values["source_memo"]),
            datetime(2026, 8, 25, tzinfo=UTC),
        )
        self.utility_rates.insert(0, record)
        self.commands[key] = (
            "utility",
            str(values["request_digest"]),
            record,
        )
        return record

    def list_exchange_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ExchangeRateRecord]:
        del cursor
        if property_id != self.property_id:
            raise ConfigurationNotFound
        return ConfigurationPage(tuple(self.exchange_rates[:limit]), None)

    def confirm_exchange_rate(
        self,
        property_id: UUID,
        *,
        record: ExchangeRateRecord,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord:
        del actor_id
        replay = self._replay(idempotency_key, "exchange", request_digest)
        if replay is not None:
            return replay  # type: ignore[return-value]
        if property_id != self.property_id:
            raise ConfigurationNotFound
        self.exchange_rates.insert(0, record)
        self.commands[idempotency_key] = ("exchange", request_digest, record)
        return record

    def get_exchange_rate_replay(
        self,
        property_id: UUID,
        *,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord | None:
        del actor_id
        if property_id != self.property_id:
            raise ConfigurationNotFound
        replay = self._replay(idempotency_key, "exchange", request_digest)
        return None if replay is None else cast(ExchangeRateRecord, replay)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=value, property_ids=frozenset({str(property_id)}))
            for value in capabilities
        ),
    )


def browser_headers(key: UUID | None = None) -> dict[str, str]:
    headers = {
        "Origin": "https://localhost",
        "Cookie": "__Host-prm_csrf=configuration-token",
        "X-CSRF-Token": "configuration-token",
    }
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers


def client_for(
    flow: InMemoryConfigurationFlow,
    *capabilities: str,
    exchange_rate_provider: ExchangeRateProvider | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            actor_resolver=lambda _: actor(flow.property_id, *capabilities),
            configuration_flow=flow,
            exchange_rate_provider=exchange_rate_provider,
        )
    )


def test_service_rate_requires_scoped_read_and_manage_capabilities() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    read_only = client_for(flow, "configuration.read")
    history = read_only.get(f"/api/v1/properties/{flow.property_id}/service-rates")
    assert history.status_code == 200
    assert history.headers["Cache-Control"] == "private, no-store"
    assert history.headers["Vary"] == "Cookie"
    response = read_only.post(
        f"/api/v1/properties/{flow.property_id}/service-rates",
        headers=browser_headers(uuid4()),
        json={
            "property_service_id": str(flow.service_id),
            "monthly_rate_usd_cents": 1250,
            "effective_date": "2026-09-01",
        },
    )
    assert response.status_code == 403


def test_service_rate_creation_requires_origin_csrf_and_idempotency() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "settings.manage")
    body = {
        "property_service_id": str(flow.service_id),
        "monthly_rate_usd_cents": 1250,
        "effective_date": "2026-09-01",
    }
    # Login sub-slice L5: the Origin and the CSRF pair are checked before the request is read,
    # so a change without them is refused even without its Idempotency-Key.
    for headers in ({}, {"Idempotency-Key": str(uuid4())}):
        assert (
            client.post(
                f"/api/v1/properties/{flow.property_id}/service-rates",
                headers=headers,
                json=body,
            ).status_code
            == 403
        )
    assert (
        client.post(
            f"/api/v1/properties/{flow.property_id}/service-rates",
            headers=browser_headers(),
            json=body,
        ).status_code
        == 422
    )


def test_service_rate_replay_is_stable_and_changed_input_conflicts() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "settings.manage")
    key = uuid4()
    body = {
        "property_service_id": str(flow.service_id),
        "monthly_rate_usd_cents": 1250,
        "effective_date": "2026-09-01",
        "source_memo": "Owner approved",
    }
    first = client.post(
        f"/api/v1/properties/{flow.property_id}/service-rates",
        headers=browser_headers(key),
        json=body,
    )
    replay = client.post(
        f"/api/v1/properties/{flow.property_id}/service-rates",
        headers=browser_headers(key),
        json=body,
    )
    changed = client.post(
        f"/api/v1/properties/{flow.property_id}/service-rates",
        headers=browser_headers(key),
        json={**body, "monthly_rate_usd_cents": 1300},
    )
    assert first.status_code == replay.status_code == 201
    assert first.headers["Location"] == f"/api/v1/service-rates/{first.json()['data']['id']}"
    assert first.json()["data"]["id"] == replay.json()["data"]["id"]
    assert changed.status_code == 409
    assert len(flow.service_rates) == 1


def test_utility_rate_preserves_notice_and_effective_date() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "settings.manage", "configuration.read")
    response = client.post(
        f"/api/v1/properties/{flow.property_id}/utility-rates",
        headers=browser_headers(uuid4()),
        json={
            "utility_type": "ELECTRICITY",
            "measurement_unit_code": "KWH",
            "rate_usd_per_unit": "0.25000000",
            "effective_date": "2026-10-01",
            "notice_at": "2026-09-01T09:00:00+07:00",
            "notice_evidence": "Notice ELEC-2026-09",
        },
    )
    assert response.status_code == 201
    assert response.headers["Location"] == f"/api/v1/utility-rates/{response.json()['data']['id']}"
    assert response.json()["data"]["effective_date"] == "2026-10-01"
    history = client.get(f"/api/v1/properties/{flow.property_id}/utility-rates?limit=1")
    assert history.status_code == 200
    assert history.json()["data"][0]["measurement_unit_code"] == "KWH"


def test_exchange_confirmation_applies_markup_and_both_ceilings() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "exchange_rates.manage", "configuration.read")
    response = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(uuid4()),
        json={
            "reference_rate_khr_per_usd": "4062.500000",
            "rate_source": "ABA_EQUIVALENT_MANUAL",
            "source_reference": "ABA fallback evidence",
            "applicable_at": "2026-08-25T10:00:00+07:00",
            "automatic_source_unavailable": True,
            "fallback_reason": "Automatic ABA-equivalent source timed out",
            "usd_amount_cents": 10001,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["system_rate_khr_per_usd"] == 4083
    assert response.json()["data"]["unrounded_payable_khr"] == "408340.83"
    assert response.json()["data"]["payable_khr"] == 408341
    history = client.get(f"/api/v1/properties/{flow.property_id}/exchange-rates")
    assert history.json()["data"][0]["source_reference"] == "ABA fallback evidence"
    assert history.json()["data"][0]["fallback_reason"] == (
        "Automatic ABA-equivalent source timed out"
    )


def test_lists_are_bounded_and_reject_invalid_cursor_or_limit() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "configuration.read")
    assert (
        client.get(f"/api/v1/properties/{flow.property_id}/service-rates?limit=101").status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/properties/{flow.property_id}/service-rates?unknown=true").status_code
        == 400
    )
    assert (
        client.get(f"/api/v1/properties/{flow.property_id}/service-rates?limit=25").status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/properties/{flow.property_id}/service-rates?cursor={'x' * 257}"
        ).status_code
        == 422
    )
    with pytest.raises(ValueError, match="Invalid cursor"):
        PostgresConfigurationFlow("unused").list_service_rates(
            flow.property_id, limit=25, cursor="not-base64"
        )


def test_detail_routes_do_not_disclose_record_existence_without_scope() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    rate = ServiceRateRecord(
        uuid4(),
        flow.property_id,
        flow.service_id,
        "TRASH_COLLECTION",
        "Trash Collection",
        1250,
        date(2026, 9, 1),
        None,
        datetime(2026, 8, 25, tzinfo=UTC),
    )
    flow.service_rates.append(rate)
    client = client_for(flow)
    assert client.get(f"/api/v1/service-rates/{rate.id}").status_code == 404
    assert client.get(f"/api/v1/service-rates/{uuid4()}").status_code == 404


def test_utility_notice_and_manual_exchange_evidence_fail_before_flow() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "settings.manage", "exchange_rates.manage")
    utility = client.post(
        f"/api/v1/properties/{flow.property_id}/utility-rates",
        headers=browser_headers(uuid4()),
        json={
            "utility_type": "WATER",
            "measurement_unit_code": "M3",
            "rate_usd_per_unit": "0.5",
            "effective_date": "2026-09-01",
            "notice_at": "2026-09-01T00:00:00+07:00",
            "notice_evidence": "Late notice",
        },
    )
    manual = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(uuid4()),
        json={
            "reference_rate_khr_per_usd": "4062.5",
            "rate_source": "ABA_EQUIVALENT_MANUAL",
            "applicable_at": "2026-08-25T10:00:00+07:00",
            "automatic_source_unavailable": True,
            "fallback_reason": "Automatic source unavailable",
            "usd_amount_cents": 100,
        },
    )
    assert utility.status_code == 422
    assert manual.status_code == 422
    assert flow.utility_rates == []
    assert flow.exchange_rates == []


@dataclass(slots=True)
class StaticExchangeRateProvider:
    quote: ExchangeRateQuote | None

    def current_sell_rate(self) -> ExchangeRateQuote:
        if self.quote is None:
            raise ExchangeRateSourceUnavailable
        return self.quote


def test_automatic_exchange_evidence_is_server_owned() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    available_quote = ExchangeRateQuote(
        Decimal("4062.500000"),
        "ABA automatic quote 2026-08-25T10:00+07:00",
        datetime(2026, 8, 25, 3, tzinfo=UTC),
    )
    provider = StaticExchangeRateProvider(available_quote)
    client = client_for(
        flow,
        "exchange_rates.manage",
        exchange_rate_provider=provider,
    )
    key = uuid4()
    response = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(key),
        json={"rate_source": "ABA_AUTOMATIC", "usd_amount_cents": 10001},
    )
    spoofed = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(uuid4()),
        json={
            "rate_source": "ABA_AUTOMATIC",
            "reference_rate_khr_per_usd": "1",
            "usd_amount_cents": 10001,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["reference_rate_khr_per_usd"] == "4062.500000"
    assert response.json()["data"]["source_reference"].startswith("ABA automatic")
    assert spoofed.status_code == 422

    provider.quote = None
    replay = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(key),
        json={"rate_source": "ABA_AUTOMATIC", "usd_amount_cents": 10001},
    )
    assert replay.status_code == 200
    assert replay.json()["data"] == response.json()["data"]

    provider.quote = available_quote
    manual_while_available = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(uuid4()),
        json={
            "rate_source": "ABA_EQUIVALENT_MANUAL",
            "reference_rate_khr_per_usd": "4062.5",
            "source_reference": "manual evidence",
            "applicable_at": "2026-08-25T10:00:00+07:00",
            "automatic_source_unavailable": True,
            "fallback_reason": "Caller assertion cannot override the provider",
            "usd_amount_cents": 10001,
        },
    )
    assert manual_while_available.status_code == 409


def test_automatic_exchange_fails_closed_when_provider_is_unavailable() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "exchange_rates.manage")
    response = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(uuid4()),
        json={"rate_source": "ABA_AUTOMATIC", "usd_amount_cents": 10001},
    )
    assert response.status_code == 503
    assert flow.exchange_rates == []


def test_manual_exchange_replay_is_stable_after_provider_recovers() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    provider = StaticExchangeRateProvider(None)
    client = client_for(
        flow,
        "exchange_rates.manage",
        exchange_rate_provider=provider,
    )
    key = uuid4()
    body = {
        "rate_source": "ABA_EQUIVALENT_MANUAL",
        "reference_rate_khr_per_usd": "4062.5",
        "source_reference": "manual evidence",
        "applicable_at": "2026-08-25T10:00:00+07:00",
        "automatic_source_unavailable": True,
        "fallback_reason": "Automatic source was unavailable",
        "usd_amount_cents": 10001,
    }
    first = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(key),
        json=body,
    )
    provider.quote = ExchangeRateQuote(
        Decimal("4065.000000"),
        "Recovered ABA automatic quote",
        datetime(2026, 8, 25, 4, tzinfo=UTC),
    )
    replay = client.post(
        f"/api/v1/properties/{flow.property_id}/exchange-rates:confirm",
        headers=browser_headers(key),
        json=body,
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    assert len(flow.exchange_rates) == 1


def test_configured_services_are_bounded_and_request_meta_is_canonical() -> None:
    flow = InMemoryConfigurationFlow(uuid4())
    client = client_for(flow, "configuration.read")
    response = client.get(
        f"/api/v1/properties/{flow.property_id}/configured-services?limit=1",
        headers={"X-Request-ID": "configuration-services"},
    )
    history = client.get(
        f"/api/v1/properties/{flow.property_id}/service-rates?limit=1",
        headers={"X-Request-ID": "configuration-history"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["service_code"] == "TRASH_COLLECTION"
    assert response.json()["meta"] == {"request_id": "configuration-services"}
    assert response.json()["page"] == {"limit": 1, "next_cursor": "configured-next"}
    continuation = client.get(
        f"/api/v1/properties/{flow.property_id}/configured-services?limit=1&cursor=configured-next"
    )
    assert continuation.json()["data"][0]["service_code"] == "WIFI"
    assert continuation.json()["page"] == {"limit": 1, "next_cursor": None}
    assert history.json()["meta"] == {"request_id": "configuration-history"}
    assert history.json()["page"] == {"limit": 1, "next_cursor": None}
