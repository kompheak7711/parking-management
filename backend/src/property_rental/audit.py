"""Immutable audit-event domain contract and append service."""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias
from uuid import UUID, uuid4

from property_rental.business_time import property_business_date

AuditScalar: TypeAlias = str | int | bool | None
AuditValue: TypeAlias = AuditScalar | tuple["AuditValue", ...] | Mapping[str, "AuditValue"]
AuditSource: TypeAlias = Literal["UI", "API", "SCHEDULED", "ADMINISTRATIVE"]
FORBIDDEN_AUDIT_STATE_KEYS = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "client_secret",
        "credential",
        "password",
        "password_hash",
        "password_verifier",
        "private_key",
        "recovery_code",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "token",
        "totp_secret",
    }
)
FORBIDDEN_AUDIT_KEY_TOKENS = frozenset(
    re.sub(r"[^a-z0-9]", "", key) for key in FORBIDDEN_AUDIT_STATE_KEYS
) | {
    "authtoken",
    "accesscode",
    "apitoken",
    "cvc",
    "cvv",
    "mfacode",
    "otp",
    "passcode",
    "passphrase",
    "passwd",
    "pin",
    "pwd",
    "securitycode",
    "resetcode",
    "tokenvalue",
    "unlockcode",
    "verificationcode",
}
FORBIDDEN_AUDIT_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(?:password|passphrase|secret|api[ _-]?key|access[ _-]?token|"
        r"refresh[ _-]?token|authorization|recovery[ _-]?code)\s*[:=]\s*\S+"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(?:sk_(?:live|test)|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/=]{32,}(?![A-Za-z0-9])"),
)
AUDIT_NUMERIC_FIELD_KEYS = frozenset(
    {
        "amount",
        "balance",
        "basis_points",
        "consumption",
        "count",
        "days",
        "exchange_rate",
        "lines",
        "percentage",
        "quantity",
        "rate",
        "reading",
        "sequence",
        "total",
        "version",
    }
)
AUDIT_NUMERIC_FIELD_SUFFIXES = (
    "_amount",
    "_balance",
    "_basis_points",
    "_cents",
    "_consumption",
    "_count",
    "_days",
    "_duration",
    "_hours",
    "_minutes",
    "_months",
    "_percentage",
    "_quantity",
    "_rate",
    "_reading",
    "_seconds",
    "_sequence",
    "_total",
    "_version",
    "_years",
)


@dataclass(frozen=True, slots=True)
class AuditEventCommand:
    """Minimum content required to record one business-significant event."""

    actor_id: UUID
    property_id: UUID
    action: str
    target_type: str
    target_id: UUID
    reason: str
    authorization_reference: str | None
    previous_state: object
    resulting_state: object
    correlation_id: UUID
    outcome: str
    source: AuditSource
    authorization_evidence: object | None = None
    linked_source_event_id: UUID | None = None
    customer_id: UUID | None = None
    unit_id: UUID | None = None
    lease_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Permanent immutable snapshot passed to append-only persistence."""

    event_id: UUID
    actor_id: UUID
    property_id: UUID
    action: str
    target_type: str
    target_id: UUID
    occurred_at: datetime
    business_date: date
    reason: str
    authorization_reference: str | None
    previous_state: AuditValue
    resulting_state: AuditValue
    correlation_id: UUID
    outcome: str
    source: AuditSource
    authorization_evidence: AuditValue | None
    linked_source_event_id: UUID | None
    customer_id: UUID | None = None
    unit_id: UUID | None = None
    lease_id: UUID | None = None


class AuditEventAppender(Protocol):
    """Persistence boundary intentionally exposing append and no mutation operation."""

    def append(self, event: AuditEvent) -> None:
        """Persist one event in the caller's current transaction."""
        ...


class AuditCursor(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class AuditConnection(Protocol):
    def execute(self, query: str, parameters: tuple[object, ...]) -> AuditCursor: ...


class PostgresAuditEventAppender:
    """Append through the caller's existing PostgreSQL transaction."""

    def __init__(self, connection: AuditConnection) -> None:
        self._connection = connection

    def append(self, event: AuditEvent) -> None:
        occurred_at = _validate_audit_event_for_persistence(event)
        self._connection.execute(
            """
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source,
                outcome, authorization_evidence, linked_source_event_id,
                customer_id, unit_id, lease_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb, %s,
                      %s, %s, %s)
            """,
            (
                event.event_id,
                occurred_at,
                event.business_date,
                event.actor_id,
                event.action,
                event.target_type,
                event.target_id,
                event.reason,
                event.authorization_reference,
                event.property_id,
                _json_text(event.previous_state),
                _json_text(event.resulting_state),
                event.correlation_id,
                event.source,
                event.outcome,
                (
                    None
                    if event.authorization_evidence is None
                    else _json_text(event.authorization_evidence)
                ),
                event.linked_source_event_id,
                event.customer_id,
                event.unit_id,
                event.lease_id,
            ),
        )


class AuditEventAppendService:
    """Validate, snapshot, and append complete audit content exactly once."""

    def __init__(
        self,
        *,
        appender: AuditEventAppender,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._appender = appender
        self._clock = clock
        self._event_id_factory = event_id_factory

    def append(self, command: AuditEventCommand) -> AuditEvent:
        """Create an immutable event and append it through the transaction boundary."""
        self._validate_required_content(command)
        instant = self._clock()
        if instant.utcoffset() is None:
            raise ValueError("audit event timestamp must be timezone-aware")

        event = AuditEvent(
            event_id=self._event_id_factory(),
            actor_id=command.actor_id,
            property_id=command.property_id,
            action=command.action,
            target_type=command.target_type,
            target_id=command.target_id,
            occurred_at=instant.astimezone(UTC),
            business_date=property_business_date(instant),
            reason=command.reason,
            authorization_reference=command.authorization_reference,
            previous_state=_freeze_audit_value(command.previous_state, "previous_state"),
            resulting_state=_freeze_audit_value(command.resulting_state, "resulting_state"),
            correlation_id=command.correlation_id,
            outcome=command.outcome,
            source=command.source,
            authorization_evidence=(
                None
                if command.authorization_evidence is None
                else _freeze_audit_value(
                    command.authorization_evidence,
                    "authorization_evidence",
                )
            ),
            linked_source_event_id=command.linked_source_event_id,
            customer_id=command.customer_id,
            unit_id=command.unit_id,
            lease_id=command.lease_id,
        )
        self._appender.append(event)
        return event

    @staticmethod
    def _validate_required_content(command: AuditEventCommand) -> None:
        required_text = {
            "action": command.action,
            "target_type": command.target_type,
            "reason": command.reason,
            "outcome": command.outcome,
        }
        for field_name, value in required_text.items():
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")
            _reject_secret_text(value, field_name)
        if command.authorization_reference is not None:
            if not command.authorization_reference.strip():
                raise ValueError("authorization_reference must not be blank")
            _reject_secret_text(
                command.authorization_reference,
                "authorization_reference",
            )
        if command.source not in {"UI", "API", "SCHEDULED", "ADMINISTRATIVE"}:
            raise ValueError("source must be a canonical audit source")
        for field_name, identifier in {
            "actor_id": command.actor_id,
            "property_id": command.property_id,
            "target_id": command.target_id,
            "correlation_id": command.correlation_id,
        }.items():
            if not isinstance(identifier, UUID):
                raise ValueError(f"{field_name} must be a UUID")
        for field_name, optional_identifier in {
            "customer_id": command.customer_id,
            "unit_id": command.unit_id,
            "lease_id": command.lease_id,
            "linked_source_event_id": command.linked_source_event_id,
        }.items():
            if optional_identifier is not None and not isinstance(optional_identifier, UUID):
                raise ValueError(f"{field_name} must be a UUID when supplied")
        if (
            command.previous_state is None
            and command.resulting_state is None
            and command.linked_source_event_id is None
        ):
            raise ValueError(
                "an audit event requires previous/resulting state or a linked source event"
            )


def _freeze_audit_value(
    value: object,
    field_path: str,
    field_key: str | None = None,
) -> AuditValue:
    """Copy JSON-compatible content into recursively immutable containers."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        _validate_classified_audit_number(field_path, field_key)
        return value
    if isinstance(value, str):
        if is_file_fingerprint(value, field_key):
            return value
        _reject_secret_text(value, field_path)
        _validate_classified_audit_text(value, field_path, field_key)
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, AuditValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field_path} object keys must be strings")
            snake_key = _normalize_audit_key(key)
            if _is_forbidden_audit_key(snake_key):
                raise ValueError(f"{field_path} contains a prohibited secret field")
            if snake_key == "account" and not isinstance(item, Mapping):
                raise ValueError(f"{field_path}.{key} must be a classified object")
            frozen[key] = _freeze_audit_value(
                item,
                f"{field_path}.{key}",
                snake_key,
            )
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_audit_value(item, f"{field_path}[{index}]", field_key)
            for index, item in enumerate(value)
        )
    raise TypeError(f"{field_path} must contain only JSON-compatible values")


def thaw_audit_value(value: AuditValue) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_audit_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_audit_value(item) for item in value]
    return value


def _json_text(value: AuditValue) -> str:
    return json.dumps(thaw_audit_value(value), separators=(",", ":"), sort_keys=True)


def is_file_fingerprint(value: str, field_key: str | None) -> bool:
    """A SHA-256 file fingerprint in a `..._sha256` field (V1-057, DL-072 answer 12).

    It is a public digest of an export file, not a secret, but its 64 hex letters look like a
    key to the secret-text patterns, so only this exact shape in such a field is let through."""
    return (
        field_key is not None
        and _normalize_audit_key(field_key).endswith("_sha256")
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def public_audit_filters(filters: Mapping[str, object]) -> dict[str, object]:
    """The search or export filters an audit event may keep (V1-057, DL-072 answer 14).

    A filter whose value the audit value rules refuse (free text typed in a search, say) is left
    out and counted in `filters_not_recorded_count`, so the event can always be read back."""
    kept: dict[str, object] = {}
    left_out = 0
    for key, value in filters.items():
        if value is None:
            continue
        try:
            _freeze_audit_value({key: value}, "filters")
        except (TypeError, ValueError):
            left_out += 1
            continue
        kept[key] = value
    if left_out:
        kept["filters_not_recorded_count"] = left_out
    return kept


def _reject_secret_text(value: str, field_path: str) -> None:
    if any(pattern.search(value) for pattern in FORBIDDEN_AUDIT_TEXT_PATTERNS):
        raise ValueError(f"{field_path} contains prohibited secret material")


def _is_forbidden_audit_key(key: str) -> bool:
    normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(token in normalized_key for token in FORBIDDEN_AUDIT_KEY_TOKENS)


def _normalize_audit_key(key: str) -> str:
    snake_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).casefold()
    return re.sub(r"[^a-z0-9]+", "_", snake_key).strip("_")


def _validate_classified_audit_text(
    value: str,
    field_path: str,
    field_key: str | None,
) -> None:
    """Permit text only when its field supplies a bounded public value class."""
    if field_key is None:
        raise ValueError(f"{field_path} text is not classified for audit persistence")
    field_key = _normalize_audit_key(field_key)
    if (field_key == "capability" or field_key.endswith("capability_ids")) and re.fullmatch(
        r"[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+", value
    ):
        return
    if field_key == "reference" and re.fullmatch(r"AUTH-[A-Z0-9-]{1,122}", value):
        return
    if field_key.endswith("_id"):
        try:
            UUID(value)
            return
        except ValueError:
            pass
    if field_key.endswith("_date") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return
    if field_key.endswith("_at"):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is not None:
                return
        except ValueError:
            pass
    if field_key in {
        "action",
        "currency",
        "outcome",
        "source",
        "status",
    } or field_key.endswith(
        (
            "_basis",
            "_category",
            "_currency",
            "_intent",
            "_kind",
            "_method",
            "_rule",
            "_source",
            "_status",
            "_step",
            "_type",
        )
    ):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", value):
            return
    if field_key in {
        "address",
        "city",
        "description",
        "email",
        "label",
        "name",
        "phone",
        "postal_code",
        "province",
        "unit_number",
    } or field_key.endswith(
        (
            "_address",
            "_description",
            "_email",
            "_label",
            "_name",
            "_number",
            "_phone",
        )
    ):
        if value.strip() and len(value) <= 512 and not re.search(r"[\x00-\x1f\x7f]", value):
            return
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        _validate_classified_audit_number(field_path, field_key)
        return
    raise ValueError(f"{field_path} text is not an approved public audit value")


def _validate_classified_audit_number(
    field_path: str,
    field_key: str | None,
) -> None:
    """Permit numeric facts only for an explicit non-credential value class."""
    if field_key is None:
        raise ValueError(f"{field_path} numeric value is not classified for audit persistence")
    snake_key = _normalize_audit_key(field_key)
    if snake_key in AUDIT_NUMERIC_FIELD_KEYS or snake_key.endswith(AUDIT_NUMERIC_FIELD_SUFFIXES):
        return
    raise ValueError(f"{field_path} numeric value is not an approved public audit value")


def _validate_audit_event_for_persistence(event: AuditEvent) -> datetime:
    """Defend the database boundary even when callers construct events directly."""
    for field_name, value in {
        "action": event.action,
        "target_type": event.target_type,
        "reason": event.reason,
        "outcome": event.outcome,
        "source": event.source,
    }.items():
        if not value.strip():
            raise ValueError(f"{field_name} must not be blank")
        _reject_secret_text(value, field_name)
    if event.authorization_reference is not None:
        if not event.authorization_reference.strip():
            raise ValueError("authorization_reference must not be blank")
        _reject_secret_text(event.authorization_reference, "authorization_reference")
    if event.source not in {"UI", "API", "SCHEDULED", "ADMINISTRATIVE"}:
        raise ValueError("source must be a canonical audit source")
    if event.occurred_at.utcoffset() is None:
        raise ValueError("audit event timestamp must be timezone-aware")
    occurred_at = event.occurred_at.astimezone(UTC)
    if event.business_date != property_business_date(occurred_at):
        raise ValueError("business_date must match the Property-local event date")
    _freeze_audit_value(event.previous_state, "previous_state")
    _freeze_audit_value(event.resulting_state, "resulting_state")
    if event.authorization_evidence is not None:
        _freeze_audit_value(event.authorization_evidence, "authorization_evidence")
    return occurred_at
