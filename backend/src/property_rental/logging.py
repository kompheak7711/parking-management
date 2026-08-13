"""Structured application logging with an explicit safe-field boundary."""

import json
import logging
from datetime import UTC, datetime
from typing import Final, TextIO

SAFE_LOG_FIELDS: Final = (
    "event",
    "service",
    "environment",
    "request_id",
    "method",
    "status_code",
    "duration_ms",
    "exception_type",
    "resource_type",
)


class SafeJsonFormatter(logging.Formatter):
    """Serialize only the fixed operational field allowlist."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "service": self.service,
            "environment": self.environment,
        }
        for field in SAFE_LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def create_application_logger(
    *,
    service: str,
    environment: str,
    level: str,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Create an isolated structured logger with fixed service context."""
    logger = logging.Logger(f"{service}.application", level=level)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeJsonFormatter(service=service, environment=environment))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
