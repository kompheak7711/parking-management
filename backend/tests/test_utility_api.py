"""Frozen V1-043 Utility resource and preview API contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.utility import (
    UtilityCalculationSnapshot,
    UtilityCalculationStatus,
    UtilityPreviewSourceKind,
)
from property_rental.utility_api import (
    BatchItemResult,
    CorrectionResult,
    MeterRecord,
    MeterReplacementEvidenceRecord,
    ReadingCorrectionRecord,
    ReadingCreateInput,
    ReadingRecord,
    ResourcePage,
    UtilityResourceIdempotencyConflict,
    UtilityResourceNotFound,
    UtilityResourceVersionConflict,
    _digest,
    _reading,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(value, frozenset({str(property_id)})) for value in capabilities
        ),
    )


def browser_headers(key: UUID | None = None) -> dict[str, str]:
    result = {
        "Origin": "https://localhost",
        "Cookie": "__Host-prm_csrf=utility-token",
        "X-CSRF-Token": "utility-token",
    }
    if key is not None:
        result["Idempotency-Key"] = str(key)
    return result


def batch_item(
    meter_id: UUID,
    reading_date: str,
    *,
    expected_meter_version: int = 1,
    reading_value: str = "20",
) -> dict[str, object]:
    return {
        "idempotency_key": str(uuid4()),
        "meter_id": str(meter_id),
        "reading": {
            "expected_meter_version": expected_meter_version,
            "reading_date": reading_date,
            "reading_value": reading_value,
            "source_kind": "MANUAL",
            "source_evidence": f"Photograph {reading_date}",
        },
    }


@dataclass(slots=True)
class InMemoryUtilityFlow:
    property_id: UUID
    unit_id: UUID = field(default_factory=uuid4)
    actor_id: UUID = field(default_factory=uuid4)
    meter: MeterRecord = field(init=False)
    readings: list[ReadingRecord] = field(default_factory=list)
    last_payload: dict[str, object] | None = None
    batch_mode: str | None = None
    batch_idempotency_key: UUID | None = None
    batch_request_digest: str | None = None
    atomic_replays: dict[UUID, tuple[str, tuple[BatchItemResult, ...]]] = field(
        default_factory=dict
    )
    version_conflict: int | None = None

    def __post_init__(self) -> None:
        now = datetime(2026, 8, 29, 12, tzinfo=UTC)
        self.meter = MeterRecord(
            uuid4(),
            self.property_id,
            self.unit_id,
            "ELECTRICITY",
            "ELEC-301",
            "KWH",
            None,
            date(2026, 7, 1),
            None,
            None,
            None,
            1,
            now,
            self.actor_id,
            now,
            self.actor_id,
            None,
            None,
            None,
            (),
        )
        self.readings.append(self._reading(date(2026, 7, 1), Decimal("10")))

    def _reading(self, reading_date: date, value: Decimal) -> ReadingRecord:
        now = datetime(2026, 8, 29, 12, tzinfo=UTC)
        return ReadingRecord(
            uuid4(),
            self.property_id,
            self.meter.id,
            self.unit_id,
            "ELECTRICITY",
            "KWH",
            reading_date,
            value,
            value,
            "MANUAL",
            "Photograph evidence",
            now,
            self.actor_id,
            1,
            now,
            self.actor_id,
            (),
        )

    def property_for_unit(self, unit_id: UUID) -> UUID:
        if unit_id != self.unit_id:
            raise UtilityResourceNotFound
        return self.property_id

    def property_for_meter(self, meter_id: UUID) -> UUID:
        if meter_id != self.meter.id:
            raise UtilityResourceNotFound
        return self.property_id

    def property_for_reading(self, reading_id: UUID) -> UUID:
        if not any(item.id == reading_id for item in self.readings):
            raise UtilityResourceNotFound
        return self.property_id

    def list_meters(self, unit_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage:
        del cursor
        self.property_for_unit(unit_id)
        return ResourcePage((self.meter,)[:limit], "next-meter" if limit == 1 else None)

    def get_meter(self, meter_id: UUID) -> MeterRecord:
        self.property_for_meter(meter_id)
        return self.meter

    def install_meter(
        self,
        unit_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord:
        del actor_id, idempotency_key, request_digest
        self.property_for_unit(unit_id)
        self.last_payload = payload
        self.meter = replace(
            self.meter,
            serial_number=str(payload["serial_number"]),
            utility_type=str(payload["utility_type"]),
        )
        return self.meter

    def replace_meter(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord:
        del actor_id, idempotency_key, request_digest
        self.property_for_meter(meter_id)
        if self.version_conflict is not None:
            raise UtilityResourceVersionConflict(self.version_conflict)
        self.last_payload = payload
        replacement = cast(dict[str, object], payload["replacement_meter"])
        return replace(
            self.meter,
            id=uuid4(),
            serial_number=str(replacement["serial_number"]),
            installed_date=cast(date, payload["replacement_date"]),
            replaced_meter_id=self.meter.id,
        )

    def list_readings(self, meter_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage:
        del cursor
        self.property_for_meter(meter_id)
        return ResourcePage(tuple(self.readings[:limit]), None)

    def record_reading(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ReadingRecord:
        del actor_id, idempotency_key, request_digest
        self.property_for_meter(meter_id)
        if self.version_conflict is not None:
            raise UtilityResourceVersionConflict(self.version_conflict)
        self.last_payload = payload
        value = self._reading(
            cast(date, payload["reading_date"]), cast(Decimal, payload["reading_value"])
        )
        self.readings.insert(0, value)
        return value

    def correct_reading(
        self,
        reading_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CorrectionResult:
        del idempotency_key, request_digest
        self.property_for_reading(reading_id)
        if self.version_conflict is not None:
            raise UtilityResourceVersionConflict(self.version_conflict)
        original = next(item for item in self.readings if item.id == reading_id)
        correction = ReadingCorrectionRecord(
            uuid4(),
            original.effective_value,
            cast(Decimal, payload["corrected_value"]),
            str(payload["reason"]),
            datetime(2026, 8, 29, 13, tzinfo=UTC),
            actor_id,
            str(payload["authorization_reference"]),
        )
        corrected = replace(
            original,
            effective_value=correction.corrected_value,
            version=original.version + 1,
            corrections=(correction,),
        )
        self.readings[self.readings.index(original)] = corrected
        return CorrectionResult(corrected, correction, ())

    def record_batch(
        self,
        property_id: UUID,
        *,
        mode: str,
        items: list[dict[str, object]],
        actor_id: UUID,
        idempotency_key: UUID | None,
        request_digest: str | None,
    ) -> tuple[BatchItemResult, ...]:
        del actor_id
        if property_id != self.property_id:
            raise UtilityResourceNotFound
        self.batch_mode = mode
        self.batch_idempotency_key = idempotency_key
        self.batch_request_digest = request_digest
        if mode == "ATOMIC_ALL":
            if idempotency_key is None or request_digest is None:
                raise ValueError("atomic batch idempotency is required")
            replay = self.atomic_replays.get(idempotency_key)
            if replay is not None:
                if replay[0] != request_digest:
                    raise UtilityResourceIdempotencyConflict
                return replay[1]
            failed_index = next(
                (index for index, item in enumerate(items) if item["meter_id"] != self.meter.id),
                None,
            )
            if failed_index is not None:
                outcomes = tuple(
                    BatchItemResult(
                        index,
                        cast(UUID, item["idempotency_key"]),
                        "FAILED",
                        error_code="NOT_FOUND" if index == failed_index else "ATOMIC_ROLLBACK",
                    )
                    for index, item in enumerate(items)
                )
                self.atomic_replays[idempotency_key] = (request_digest, outcomes)
                return outcomes
            readings = tuple(
                self._reading(
                    cast(date, cast(dict[str, object], item["reading"])["reading_date"]),
                    cast(Decimal, cast(dict[str, object], item["reading"])["reading_value"]),
                )
                for item in items
            )
            outcomes = tuple(
                BatchItemResult(
                    index,
                    cast(UUID, item["idempotency_key"]),
                    "SUCCEEDED",
                    readings[index],
                )
                for index, item in enumerate(items)
            )
            self.readings[0:0] = readings
            self.atomic_replays[idempotency_key] = (request_digest, outcomes)
            return outcomes

        results: list[BatchItemResult] = []
        for index, item in enumerate(items):
            key = cast(UUID, item["idempotency_key"])
            if item["meter_id"] != self.meter.id:
                results.append(BatchItemResult(index, key, "FAILED", error_code="NOT_FOUND"))
            else:
                results.append(BatchItemResult(index, key, "SUCCEEDED", self.readings[0]))
        return tuple(results)

    def preview(
        self,
        property_id: UUID,
        *,
        source_kind: UtilityPreviewSourceKind,
        source_id: UUID,
        generation_at: datetime,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        del source_kind, source_id, generation_at, actor
        if property_id != self.property_id:
            raise UtilityResourceNotFound
        return UtilityCalculationSnapshot(
            UtilityCalculationStatus.PENDING_FUTURE_ACTUAL_BASIS,
            self.property_id,
            self.unit_id,
            "ELECTRICITY",
            None,
            None,
            date(2026, 8, 2),
            date(2026, 8, 31),
            None,
            30,
            None,
            None,
            None,
            self.meter.id,
            uuid4(),
            None,
            (),
            (),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )


def client_for(flow: InMemoryUtilityFlow, *capabilities: str) -> TestClient:
    return TestClient(
        create_app(
            actor_resolver=lambda _: actor(flow.property_id, *capabilities),
            utility_resource_flow=flow,
        )
    )


def test_meter_routes_are_property_scoped_paginated_and_no_store() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    denied = client_for(flow)
    assert denied.get(f"/api/v1/units/{flow.unit_id}/meters").status_code == 403
    assert denied.get(f"/api/v1/meters/{flow.meter.id}").status_code == 404
    read_client = client_for(flow, "utility.read")
    response = read_client.get(f"/api/v1/units/{flow.unit_id}/meters?limit=1")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json()["page"] == {"limit": 1, "next_cursor": "next-meter"}
    assert response.json()["data"][0]["readings_url"].endswith("/readings")
    event_id = uuid4()
    boundary_id = uuid4()
    initial_id = uuid4()
    idempotency_key = uuid4()
    event = MeterReplacementEvidenceRecord(
        event_id,
        flow.meter.id,
        uuid4(),
        boundary_id,
        initial_id,
        date(2026, 8, 1),
        date(2026, 8, 2),
        3,
        "Confirmed failure",
        datetime(2026, 8, 2, 12, tzinfo=UTC),
        flow.actor_id,
        idempotency_key,
        "a" * 64,
        {"failed_boundary_reading_id": str(boundary_id)},
    )
    flow.meter = replace(flow.meter, replacement_events=(event,))
    replacement_body = read_client.get(f"/api/v1/meters/{flow.meter.id}").json()["data"][
        "replacement"
    ]
    assert replacement_body["events"] == [
        {
            "id": str(event_id),
            "failed_meter_id": str(flow.meter.id),
            "replacement_meter_id": str(event.replacement_meter_id),
            "failed_boundary_reading_id": str(boundary_id),
            "replacement_initial_reading_id": str(initial_id),
            "failure_date": "2026-08-01",
            "replacement_date": "2026-08-02",
            "expected_failed_meter_version": 3,
            "reason": "Confirmed failure",
            "occurred_at": "2026-08-02T12:00:00+00:00",
            "actor_id": str(flow.actor_id),
            "idempotency_key": str(idempotency_key),
            "request_digest": "a" * 64,
            "request_evidence": {"failed_boundary_reading_id": str(boundary_id)},
        }
    ]
    assert (
        read_client.get(f"/api/v1/units/{flow.unit_id}/meters?unexpected=true").status_code == 400
    )
    validated = read_client.get(f"/api/v1/meters/{flow.meter.id}/readings").json()["data"][0]
    assert validated["validated"] is True
    assert validated["validated_at"] == "2026-08-29T12:00:00+00:00"
    assert validated["validated_by"] == str(flow.actor_id)

    created_at = datetime(2026, 7, 2, 12, tzinfo=UTC)
    pending = _reading(
        (
            uuid4(),
            flow.property_id,
            flow.meter.id,
            flow.unit_id,
            "ELECTRICITY",
            "KWH",
            date(2026, 7, 31),
            Decimal("25.000000"),
            Decimal("25.000000"),
            "MIGRATED",
            "Published historical Utility Reading",
            None,
            None,
            1,
            created_at,
            flow.actor_id,
            [],
        )
    )
    assert pending.validated_at is None
    assert pending.validated_by is None
    flow.readings[0] = pending
    response = read_client.get(f"/api/v1/meters/{flow.meter.id}/readings")
    assert response.status_code == 200
    pending_body = response.json()["data"][0]
    assert pending_body["validated"] is False
    assert pending_body["validated_at"] is None
    assert pending_body["validated_by"] is None


def test_reading_history_preserves_mixed_pending_and_validated_shapes() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    validated = flow.readings[0]
    pending = replace(
        validated,
        id=uuid4(),
        reading_date=date(2026, 7, 31),
        original_value=Decimal("25.000000"),
        effective_value=Decimal("25.000000"),
        validated_at=None,
        validated_by=None,
    )
    flow.readings = [pending, validated]

    response = client_for(flow, "utility.read").get(f"/api/v1/meters/{flow.meter.id}/readings")

    assert response.status_code == 200
    history = response.json()["data"]
    assert len(history) == 2
    assert history[0]["id"] == str(pending.id)
    assert history[0]["validated"] is False
    assert history[0]["validated_at"] is None
    assert history[0]["validated_by"] is None
    assert history[1]["id"] == str(validated.id)
    assert history[1]["validated"] is True
    assert history[1]["validated_at"] == "2026-08-29T12:00:00+00:00"
    assert history[1]["validated_by"] == str(flow.actor_id)


def test_install_requires_capability_csrf_idempotency_and_boundary_evidence() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    client = client_for(flow, "utility_meters.manage")
    payload = {
        "utility_type": "WATER",
        "serial_number": "WATER-301",
        "measurement_unit_code": "M3",
        "description": None,
        "installed_date": "2026-08-01",
        "memo": None,
        "initial_reading": {
            "reading_date": "2026-08-01",
            "reading_value": "1.000000",
            "source_evidence": "Photograph 1",
        },
    }
    # Login sub-slice L5 (Q-2026-10-24-186): the Origin and the CSRF pair are checked before the
    # body and the headers, so without them the answer is 403 and with them a missing key is 422.
    assert client.post(f"/api/v1/units/{flow.unit_id}/meters", json=payload).status_code == 403
    assert (
        client.post(
            f"/api/v1/units/{flow.unit_id}/meters", json=payload, headers=browser_headers()
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/units/{flow.unit_id}/meters",
            json=payload,
            headers={"Idempotency-Key": str(uuid4()), "Origin": "https://localhost"},
        ).status_code
        == 403
    )
    response = client.post(
        f"/api/v1/units/{flow.unit_id}/meters",
        json=payload,
        headers=browser_headers(uuid4()),
    )
    assert response.status_code == 201
    assert response.json()["data"]["serial_number"] == "WATER-301"
    assert response.headers["Location"].startswith("/api/v1/meters/")
    initial_reading = cast(dict[str, object], payload["initial_reading"])
    invalid = {
        **payload,
        "initial_reading": {**initial_reading, "reading_date": "2026-08-02"},
    }
    assert (
        client.post(
            f"/api/v1/units/{flow.unit_id}/meters",
            json=invalid,
            headers=browser_headers(uuid4()),
        ).status_code
        == 422
    )
    item = {
        "idempotency_key": str(uuid4()),
        "meter_id": str(flow.meter.id),
        "reading": {
            "expected_meter_version": 1,
            "reading_date": "2026-08-01",
            "reading_value": "20",
            "source_evidence": "Photo",
        },
    }
    assert (
        client.post(
            f"/api/v1/properties/{flow.property_id}/utility-readings:batch",
            json={"mode": "PARTIAL", "items": [item] * 101},
            headers=browser_headers(),
        ).status_code
        == 422
    )


def test_reading_concurrency_and_correction_history_use_safe_envelopes() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    client = client_for(flow, "utility_readings.record", "utility_readings.correct")
    flow.version_conflict = 4
    response = client.post(
        f"/api/v1/meters/{flow.meter.id}/readings",
        json={
            "expected_meter_version": 1,
            "reading_date": "2026-08-01",
            "reading_value": "20",
            "source_kind": "MANUAL",
            "source_evidence": "Photo",
        },
        headers=browser_headers(uuid4()),
    )
    assert response.status_code == 412
    assert response.json()["error"]["current_version"] == 4
    flow.version_conflict = None
    reading_id = flow.readings[0].id
    corrected = client.post(
        f"/api/v1/utility-readings/{reading_id}/correct",
        json={
            "expected_version": 1,
            "corrected_value": "12",
            "reason": "Transcription error",
            "authorization_reference": "approval-1",
        },
        headers=browser_headers(uuid4()),
    )
    assert corrected.status_code == 201
    data = corrected.json()["data"]
    assert data["reading"]["original_value"] == "10"
    assert data["reading"]["effective_value"] == "12"
    assert data["correction"]["previous_value"] == "10"
    assert data["affected_calculations"] == []


def test_batch_modes_preserve_order_and_atomic_all_replay_conflict_rollback() -> None:
    partial_flow = InMemoryUtilityFlow(uuid4())
    partial_client = client_for(partial_flow, "utility_readings.record")
    partial_items = [
        batch_item(partial_flow.meter.id, "2026-08-01"),
        batch_item(uuid4(), "2026-08-01"),
    ]
    partial = partial_client.post(
        f"/api/v1/properties/{partial_flow.property_id}/utility-readings:batch",
        json={"mode": "PARTIAL", "items": partial_items},
        headers=browser_headers(),
    )
    assert partial.status_code == 200
    partial_data = partial.json()["data"]
    assert partial_data["mode"] == "PARTIAL"
    assert [item["status"] for item in partial_data["items"]] == [
        "SUCCEEDED",
        "FAILED",
    ]
    assert [item["index"] for item in partial_data["items"]] == [0, 1]
    assert [item["idempotency_key"] for item in partial_data["items"]] == [
        item["idempotency_key"] for item in partial_items
    ]
    assert partial_flow.batch_idempotency_key is None
    assert partial_flow.batch_request_digest is None

    flow = InMemoryUtilityFlow(uuid4())
    client = client_for(flow, "utility_readings.record")
    items = [
        batch_item(flow.meter.id, "2026-08-01"),
        batch_item(uuid4(), "2026-09-01", expected_meter_version=2),
    ]
    url = f"/api/v1/properties/{flow.property_id}/utility-readings:batch"
    assert (
        client.post(
            f"/api/v1/properties/{uuid4()}/utility-readings:batch",
            json={"mode": "ATOMIC_ALL", "items": items},
            headers=browser_headers(uuid4()),
        ).status_code
        == 403
    )
    assert (
        client.post(
            url,
            json={"mode": "ATOMIC_ALL", "items": items},
            headers={"Idempotency-Key": str(uuid4()), "Origin": "https://localhost"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            url,
            json={"mode": "ATOMIC_ALL", "items": items},
            headers=browser_headers(),
        ).status_code
        == 422
    )
    before = tuple(flow.readings)
    envelope_key = uuid4()
    atomic = client.post(
        url,
        json={"mode": "ATOMIC_ALL", "items": items},
        headers=browser_headers(envelope_key),
    )
    assert atomic.status_code == 200
    atomic_data = atomic.json()["data"]
    assert atomic_data["mode"] == "ATOMIC_ALL"
    outcomes = atomic_data["items"]
    assert [item["index"] for item in outcomes] == [0, 1]
    assert [item["idempotency_key"] for item in outcomes] == [
        item["idempotency_key"] for item in items
    ]
    assert [item["status"] for item in outcomes] == ["FAILED", "FAILED"]
    assert [item["error"]["code"] for item in outcomes] == [
        "ATOMIC_ROLLBACK",
        "NOT_FOUND",
    ]
    assert all(item["reading"] is None for item in outcomes)
    assert tuple(flow.readings) == before
    assert flow.batch_idempotency_key == envelope_key
    assert flow.batch_request_digest is not None
    assert len(flow.batch_request_digest) == 64

    replay = client.post(
        url,
        json={"mode": "ATOMIC_ALL", "items": items},
        headers=browser_headers(envelope_key),
    )
    assert replay.status_code == 200
    assert replay.json()["data"] == atomic.json()["data"]

    changed_items = [*items]
    changed_items[0] = {
        **changed_items[0],
        "reading": {
            **cast(dict[str, object], changed_items[0]["reading"]),
            "reading_value": "21",
        },
    }
    conflict = client.post(
        url,
        json={"mode": "ATOMIC_ALL", "items": changed_items},
        headers=browser_headers(envelope_key),
    )
    assert conflict.status_code == 409

    success_flow = InMemoryUtilityFlow(uuid4())
    success_client = client_for(success_flow, "utility_readings.record")
    success_items = [
        batch_item(success_flow.meter.id, "2026-08-01"),
        batch_item(success_flow.meter.id, "2026-09-01", expected_meter_version=2),
    ]
    success_url = f"/api/v1/properties/{success_flow.property_id}/utility-readings:batch"
    success_key = uuid4()
    success = success_client.post(
        success_url,
        json={"mode": "ATOMIC_ALL", "items": success_items},
        headers=browser_headers(success_key),
    )
    assert success.status_code == 200
    success_data = success.json()["data"]
    assert success_data["mode"] == "ATOMIC_ALL"
    success_outcomes = success_data["items"]
    assert [item["index"] for item in success_outcomes] == [0, 1]
    assert [item["idempotency_key"] for item in success_outcomes] == [
        item["idempotency_key"] for item in success_items
    ]
    assert [item["status"] for item in success_outcomes] == ["SUCCEEDED", "SUCCEEDED"]
    assert [item["error"] for item in success_outcomes] == [None, None]
    reading_ids = [item["reading"]["id"] for item in success_outcomes]
    assert len(set(reading_ids)) == 2
    reading_count = len(success_flow.readings)
    success_replay = success_client.post(
        success_url,
        json={"mode": "ATOMIC_ALL", "items": success_items},
        headers=browser_headers(success_key),
    )
    assert success_replay.status_code == 200
    assert [item["reading"]["id"] for item in success_replay.json()["data"]["items"]] == reading_ids
    assert len(success_flow.readings) == reading_count


def test_preview_is_non_persisted_pending_and_requires_calculate_capability() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    payload = {
        "property_id": str(flow.property_id),
        "source_kind": "ESTIMATION_CASE",
        "source_id": str(uuid4()),
        "generation_at": "2026-08-31T12:00:00+07:00",
    }
    denied = client_for(flow)
    assert (
        denied.post(
            "/api/v1/utility-billing/preview", json=payload, headers=browser_headers()
        ).status_code
        == 403
    )
    response = client_for(flow, "utility.calculate").post(
        "/api/v1/utility-billing/preview", json=payload, headers=browser_headers()
    )
    assert response.status_code == 200
    assert response.json()["meta"]["persisted"] is False
    assert response.json()["meta"]["issued"] is False
    assert response.json()["data"]["status"] == "PENDING_FUTURE_ACTUAL_BASIS"
    assert response.json()["data"]["amount_usd_cents"] is None


def test_unsupported_utility_and_unbounded_batch_are_rejected() -> None:
    flow = InMemoryUtilityFlow(uuid4())
    client = client_for(flow, "utility_meters.manage", "utility_readings.record")
    install = {
        "utility_type": "GAS",
        "serial_number": "GAS-1",
        "measurement_unit_code": "M3",
        "installed_date": "2026-08-01",
        "initial_reading": {
            "reading_date": "2026-08-01",
            "reading_value": "0",
            "source_evidence": "Photo",
        },
    }
    assert (
        client.post(
            f"/api/v1/units/{flow.unit_id}/meters",
            json=install,
            headers=browser_headers(uuid4()),
        ).status_code
        == 422
    )


def test_idempotency_digest_binds_action_and_target_resource() -> None:
    reading = ReadingCreateInput(
        expected_meter_version=1,
        reading_date=date(2026, 8, 1),
        reading_value=Decimal("20"),
        source_evidence="Photo",
    )
    first_meter = uuid4()
    assert _digest(reading, "RECORD_READING", first_meter) == _digest(
        reading, "RECORD_READING", first_meter
    )
    assert _digest(reading, "RECORD_READING", first_meter) != _digest(
        reading, "RECORD_READING", uuid4()
    )
    assert _digest(reading, "RECORD_READING", first_meter) != _digest(
        reading, "CORRECT_READING", first_meter
    )
