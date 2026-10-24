"""`GET /api/v1/operations/status`: the health page data (V1-059; API-081, UI-093, DL-071).

Only a signed-in user holding `operations.status.read` (the Owner and Manager bundles, DL-081
Q-2026-10-21-158 (a)) gets the answer. It shows the build, the database state, the backup,
off-host copy, restore test and migration records, the scheduled-job times seen by the
operations check, the Telegram state and the warnings, worked out by the same rules the Telegram
alerts use. It never shows a secret, a database address, a file path or a Customer detail.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, Request, Response, status

from property_rental.access_control import OPERATIONS_STATUS_READ_CAPABILITY
from property_rental.identity import ActorResolver, AuthorizationRequirement, is_authorized
from property_rental.operations_status import (
    HealthWarning,
    evaluate_warnings,
    format_time,
    read_all_status,
    utc_now,
)
from property_rental.settings import Settings

RECORD_FIELDS: Final = (
    "last_attempt_at",
    "last_outcome",
    "last_failure_code",
    "last_success_at",
    "backup_id",
    "schema_revision",
    "revision",
)
STATUS_NOT_SET_UP: Final = HealthWarning(
    code="operations_status_not_set_up",
    message="The health records are not set up on this computer yet.",
    critical=False,
)


def _record(file: Mapping[str, object] | None) -> dict[str, object] | None:
    if file is None:
        return None
    return {field: file[field] for field in RECORD_FIELDS if field in file}


def create_operations_status_router(
    actor_resolver: ActorResolver,
    settings: Settings,
    readiness_check: Callable[[str], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["operations"])

    @router.get("/operations/status", summary="Operational status for the health page")
    def operations_status(request: Request, response: Response) -> dict[str, object]:
        actor = actor_resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not is_authorized(
            actor, AuthorizationRequirement(capability=OPERATIONS_STATUS_READ_CAPABILITY)
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        response.headers["Cache-Control"] = "private, no-store"

        database = "not_configured"
        if settings.database_url is not None:
            try:
                readiness_check(settings.database_url.get_secret_value())
                database = "ok"
            except Exception:
                database = "unavailable"

        now = utc_now()
        directory = settings.operations_status_directory
        files = read_all_status(Path(directory)) if directory is not None else {}
        warnings = evaluate_warnings(files, now) if directory is not None else [STATUS_NOT_SET_UP]
        if database == "unavailable" and all(w.code != "database_unavailable" for w in warnings):
            warnings.insert(
                0,
                HealthWarning(
                    code="database_unavailable",
                    message="The database is not answering.",
                    critical=True,
                ),
            )
        checks = files.get("checks") or {}
        telegram_value = checks.get("telegram")
        telegram: dict[str, object] = telegram_value if isinstance(telegram_value, dict) else {}
        return {
            "data": {
                "build_version": settings.build_version,
                "environment": settings.environment,
                "generated_at": format_time(now),
                "database": database,
                "backup": _record(files.get("backup")),
                "offhost_daily": _record(files.get("offhost-daily")),
                "offhost_weekly": _record(files.get("offhost-weekly")),
                "restore_test": _record(files.get("restore-test")),
                "migration": _record(files.get("migration")),
                "last_check_at": checks.get("checked_at"),
                "schema_revision": checks.get("schema_revision"),
                "scheduled_jobs": {
                    "billing_last_success_at": checks.get("billing_last_success_at"),
                    "reservation_expiration_last_success_at": checks.get(
                        "reservation_expiration_last_success_at"
                    ),
                },
                "telegram": {
                    "configured": telegram.get("configured") is True,
                    "last_delivery_outcome": telegram.get("last_delivery_outcome"),
                    "last_attempt_at": telegram.get("last_attempt_at"),
                },
                "warnings": [
                    {"code": w.code, "message": w.message, "critical": w.critical} for w in warnings
                ],
            },
            "meta": {"request_id": request.state.request_id},
        }

    return router
