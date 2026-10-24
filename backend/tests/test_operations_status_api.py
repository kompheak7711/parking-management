"""V1-059 `GET /api/v1/operations/status` (API-081, UI-093, DL-071, DL-081 Q-2026-10-21-158)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.operations_status import format_time, utc_now, write_status
from property_rental.settings import Settings

PATH = "/api/v1/operations/status"
READER = AuthenticatedActor(
    actor_id=str(uuid.uuid4()),
    capability_grants=frozenset({CapabilityGrant(capability="operations.status.read")}),
)
OTHER = AuthenticatedActor(
    actor_id=str(uuid.uuid4()),
    capability_grants=frozenset({CapabilityGrant(capability="property.read")}),
)


def client(actor: AuthenticatedActor | None, settings: Settings | None = None) -> TestClient:
    return TestClient(create_app(settings or Settings(), actor_resolver=lambda _: actor))


def test_only_a_signed_in_holder_of_operations_status_read_gets_the_status() -> None:
    assert client(None).get(PATH).status_code == 401
    assert client(OTHER).get(PATH).status_code == 403
    # No database setting, also when the PostgreSQL run sets APP_DATABASE_URL (merge, DL-082).
    answer = client(READER, Settings(database_url=None)).get(PATH)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    data = answer.json()["data"]
    assert data["database"] == "not_configured"
    assert data["warnings"] == [
        {
            "code": "operations_status_not_set_up",
            "message": "The health records are not set up on this computer yet.",
            "critical": False,
        }
    ]


def test_the_status_shows_records_and_warnings_without_secrets_or_paths(tmp_path: Path) -> None:
    now = format_time(utc_now())
    write_status(
        tmp_path,
        "backup",
        {
            "last_outcome": "failed",
            "last_failure_code": "dump_failed",
            "last_success_at": now,
            "backup_id": "prm-20270315T030000Z",
            "schema_revision": "20270204_192",
        },
    )
    for name in ("offhost-daily", "offhost-weekly", "restore-test"):
        write_status(
            tmp_path,
            name,
            {
                "last_outcome": "succeeded",
                "last_success_at": now,
            },
        )
    write_status(
        tmp_path,
        "checks",
        {
            "checked_at": now,
            "found_warnings": ["low_disk_space"],
            "disks": [{"path": "/var/lib/prm", "free_percent": 3.0, "low": True}],
            "telegram": {"configured": True, "last_delivery_outcome": "sent"},
            "billing_last_success_at": now,
        },
    )

    def database_down(_: str) -> None:
        raise OSError("connection to postgresql://runtime:pw@db/prm refused")

    settings = Settings(
        database_url="postgresql://runtime:pw@db/prm",
        operations_status_directory=str(tmp_path),
        build_version="v1.0.0-rc1",
    )
    app = create_app(settings, readiness_check=database_down, actor_resolver=lambda _: READER)
    answer = TestClient(app).get(PATH)
    assert answer.status_code == 200
    data = answer.json()["data"]
    assert data["build_version"] == "v1.0.0-rc1"
    assert data["database"] == "unavailable"
    assert data["backup"]["last_failure_code"] == "dump_failed"
    assert data["scheduled_jobs"]["billing_last_success_at"] == now
    assert data["telegram"]["configured"] is True
    assert [w["code"] for w in data["warnings"]] == [
        "database_unavailable",
        "backup_failed",
        "low_disk_space",
    ]
    text = json.dumps(answer.json())
    for secret_or_path in ("pw", "postgresql://", "/var/lib/prm", str(tmp_path)):
        assert secret_or_path not in text
