"""Domain tests for immutable audit-event recording."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from property_rental.audit import (
    AuditCursor,
    AuditEvent,
    AuditEventAppendService,
    AuditEventCommand,
    PostgresAuditEventAppender,
)


class RecordingAppender:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def audit_command() -> AuditEventCommand:
    return AuditEventCommand(
        actor_id=UUID("00000000-0000-0000-0000-000000000017"),
        property_id=UUID("00000000-0000-0000-0000-000000000001"),
        action="invoice.issued",
        target_type="invoice",
        target_id=UUID("00000000-0000-0000-0000-000000000041"),
        reason="approved billing run",
        authorization_reference="AUTH-INVOICE-001",
        previous_state={"status": "draft", "lines": [1000, 250]},
        resulting_state={"status": "issued", "lines": [1000, 250]},
        correlation_id=UUID("00000000-0000-0000-0000-000000000083"),
        outcome="recorded",
        source="API",
        authorization_evidence={"capability": "invoice.issue"},
        linked_source_event_id=UUID("00000000-0000-0000-0000-000000000041"),
    )


def test_append_records_complete_content_with_utc_and_property_date() -> None:
    appender = RecordingAppender()
    instant = datetime.fromisoformat("2026-08-23T18:30:00+00:00")
    event_id = UUID("00000000-0000-0000-0000-000000000083")
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: instant,
        event_id_factory=lambda: event_id,
    )

    event = service.append(audit_command())

    assert appender.events == [event]
    assert event.event_id == event_id
    assert event.actor_id == UUID("00000000-0000-0000-0000-000000000017")
    assert event.property_id == UUID("00000000-0000-0000-0000-000000000001")
    assert event.action == "invoice.issued"
    assert event.target_type == "invoice"
    assert event.target_id == UUID("00000000-0000-0000-0000-000000000041")
    assert event.occurred_at == instant.astimezone(UTC)
    assert event.business_date.isoformat() == "2026-08-24"
    assert event.reason == "approved billing run"
    assert event.authorization_reference == "AUTH-INVOICE-001"
    assert event.previous_state == {"status": "draft", "lines": (1000, 250)}
    assert event.resulting_state == {"status": "issued", "lines": (1000, 250)}
    assert event.correlation_id == UUID("00000000-0000-0000-0000-000000000083")
    assert event.outcome == "recorded"
    assert event.source == "API"
    assert event.authorization_evidence == {"capability": "invoice.issue"}
    assert event.linked_source_event_id == UUID("00000000-0000-0000-0000-000000000041")


def test_append_snapshots_state_into_recursively_immutable_content() -> None:
    appender = RecordingAppender()
    lines = [1000]
    previous: dict[str, object] = {"status": "draft", "lines": lines}
    command = replace(audit_command(), previous_state=previous)
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    event = service.append(command)
    previous["status"] = "changed-after-append"
    lines.append(9999)

    assert event.previous_state == {"status": "draft", "lines": (1000,)}
    with pytest.raises(TypeError):
        event.previous_state["status"] = "silently-rewritten"
    with pytest.raises(FrozenInstanceError):
        event.reason = "silently-rewritten"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "command"),
    [
        ("action", replace(audit_command(), action="  ")),
        ("target_type", replace(audit_command(), target_type="  ")),
        ("reason", replace(audit_command(), reason="  ")),
        ("outcome", replace(audit_command(), outcome="  ")),
    ],
)
def test_append_rejects_blank_minimum_content(field_name: str, command: AuditEventCommand) -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match=field_name):
        service.append(command)

    assert appender.events == []


def test_append_rejects_naive_timestamp_before_persistence() -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.append(audit_command())

    assert appender.events == []


def test_append_requires_snapshot_or_linked_source_event() -> None:
    service = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="previous/resulting state or a linked source"):
        service.append(
            replace(
                audit_command(),
                previous_state=None,
                resulting_state=None,
                linked_source_event_id=None,
            )
        )


def test_append_rejects_mutable_or_non_json_state_values() -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(TypeError, match="previous_state"):
        service.append(replace(audit_command(), previous_state={"amount": 1.25}))

    assert appender.events == []


@pytest.mark.parametrize(
    "secret_key",
    [
        "password",
        "access_token",
        "accessToken",
        "auth_token",
        "apiKey",
        "client-secret",
        "authorization",
        "access_code",
        "recovery code",
        "reset_code",
        "passwd",
        "token",
    ],
)
def test_append_rejects_secret_bearing_snapshot_fields(secret_key: str) -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="prohibited secret field"):
        service.append(
            replace(
                audit_command(),
                resulting_state={"account": {secret_key: "must-not-persist"}},
            )
        )

    assert appender.events == []


@pytest.mark.parametrize(
    "secret_key",
    [
        "otp",
        "otp_value",
        "pin",
        "pin_number",
        "mfa_code",
        "mfa_code_value",
        "pwd",
        "pwd_value",
        "security_code",
    ],
)
def test_append_rejects_numeric_secret_bearing_snapshot_fields(secret_key: str) -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="prohibited secret field"):
        service.append(
            replace(
                audit_command(),
                resulting_state={"account": {secret_key: 123456}},
            )
        )

    assert appender.events == []


def test_append_rejects_unknown_snapshot_fields_by_default() -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="not an approved public audit value"):
        service.append(
            replace(
                audit_command(),
                resulting_state={"arbitrary_payload": "not classified"},
            )
        )

    assert appender.events == []


@pytest.mark.parametrize(
    ("field_name", "command"),
    [
        ("reason", replace(audit_command(), reason="password=hunter2")),
        (
            "reason",
            replace(
                audit_command(),
                reason="Authorization: Bearer abcdefghijklmnop",
            ),
        ),
        (
            "authorization_reference",
            replace(
                audit_command(),
                authorization_reference="apiKey=abcdefghijklmnop",
            ),
        ),
        (
            "resulting_state",
            replace(
                audit_command(),
                resulting_state={"note": "Bearer abcdefghijklmnop"},
            ),
        ),
        (
            "authorization_evidence",
            replace(
                audit_command(),
                authorization_evidence={"proof": "eyJabcdefgh.abcdefgh.abcdefgh"},
            ),
        ),
        (
            "resulting_state",
            replace(
                audit_command(),
                resulting_state={"status": "sk_live_abcdefghijklmnop"},
            ),
        ),
    ],
)
def test_append_rejects_secret_material_in_free_form_values(
    field_name: str,
    command: AuditEventCommand,
) -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="prohibited secret material"):
        service.append(command)

    assert appender.events == []


def test_append_accepts_classified_financial_and_operational_facts() -> None:
    appender = RecordingAppender()
    service = AuditEventAppendService(
        appender=appender,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    event = service.append(
        replace(
            audit_command(),
            resulting_state={
                "calculation": {
                    "basis_points": "2000",
                    "inputs": {"monthly_amount_usd_cents": 50000},
                    "percentage": "20.0",
                    "rounding_rule": "ROUND_HALF_UP",
                },
                "payer_intent": "CURRENT_INVOICE",
                "allocation_category": "RENT",
                "ordering_step": "PET_RELATED_FIRST",
                "consumption": "12.500000",
                "balance": "125.00",
                "exchange_rate": "4100.125000",
                "settlement": {"amount_usd_cents": 12500},
            },
        )
    )

    assert event.resulting_state == {
        "calculation": {
            "basis_points": "2000",
            "inputs": {"monthly_amount_usd_cents": 50000},
            "percentage": "20.0",
            "rounding_rule": "ROUND_HALF_UP",
        },
        "payer_intent": "CURRENT_INVOICE",
        "allocation_category": "RENT",
        "ordering_step": "PET_RELATED_FIRST",
        "consumption": "12.500000",
        "balance": "125.00",
        "exchange_rate": "4100.125000",
        "settlement": {"amount_usd_cents": 12500},
    }


@pytest.mark.parametrize("value", [123456, "123456"])
def test_append_rejects_unclassified_numeric_authentication_secret(value: object) -> None:
    service = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="numeric value is not an approved public"):
        service.append(
            replace(
                audit_command(),
                resulting_state={"account": {"one_time_code": value}},
            )
        )


def test_append_accepts_safe_business_identity_fields() -> None:
    service = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    event = service.append(
        replace(
            audit_command(),
            previous_state={"name": "Old Name", "unit_number": "A-11"},
            resulting_state={
                "name": "New Name",
                "unit_number": "A-12",
                "email": "tenant@example.test",
                "phone": "+855 12 345 678",
            },
        )
    )

    assert event.previous_state == {"name": "Old Name", "unit_number": "A-11"}
    assert event.resulting_state == {
        "name": "New Name",
        "unit_number": "A-12",
        "email": "tenant@example.test",
        "phone": "+855 12 345 678",
    }


def test_postgres_appender_rejects_direct_event_with_secret_before_insert() -> None:
    class RejectRecordingConnection:
        def __init__(self) -> None:
            self.called = False

        def execute(self, query: str, parameters: tuple[object, ...]) -> AuditCursor:
            del query, parameters
            self.called = True
            raise AssertionError("unsafe event reached persistence")

    connection = RejectRecordingConnection()
    event = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    ).append(audit_command())

    with pytest.raises(ValueError, match="prohibited secret material"):
        PostgresAuditEventAppender(connection).append(replace(event, reason="password=hunter2"))

    assert connection.called is False


def test_postgres_appender_rejects_direct_blank_authorization_reference() -> None:
    class RejectRecordingConnection:
        def __init__(self) -> None:
            self.called = False

        def execute(self, query: str, parameters: tuple[object, ...]) -> AuditCursor:
            del query, parameters
            self.called = True
            raise AssertionError("blank authorization reference reached persistence")

    connection = RejectRecordingConnection()
    event = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    ).append(audit_command())

    with pytest.raises(ValueError, match="authorization_reference must not be blank"):
        PostgresAuditEventAppender(connection).append(replace(event, authorization_reference="   "))

    assert connection.called is False


def test_postgres_appender_enforces_time_invariants_and_normalizes_utc() -> None:
    class EmptyCursor:
        def fetchall(self) -> list[tuple[object, ...]]:
            return []

        def fetchone(self) -> tuple[object, ...] | None:
            return None

    class RecordingConnection:
        def __init__(self) -> None:
            self.parameters: list[tuple[object, ...]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> AuditCursor:
            del query
            self.parameters.append(parameters)
            return EmptyCursor()

    event = AuditEventAppendService(
        appender=RecordingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    ).append(audit_command())
    connection = RecordingConnection()
    appender = PostgresAuditEventAppender(connection)

    with pytest.raises(ValueError, match="timezone-aware"):
        appender.append(replace(event, occurred_at=datetime(2026, 8, 23)))
    with pytest.raises(ValueError, match="business_date"):
        appender.append(replace(event, business_date=event.business_date.replace(day=22)))

    offset_event = replace(
        event,
        occurred_at=datetime.fromisoformat("2026-08-23T18:30:00+07:00"),
    )
    appender.append(offset_event)

    assert len(connection.parameters) == 1
    assert connection.parameters[0][1] == datetime(2026, 8, 23, 11, 30, tzinfo=UTC)


def test_append_propagates_persistence_failure() -> None:
    class FailingAppender:
        def append(self, event: AuditEvent) -> None:
            raise RuntimeError("audit write failed")

    service = AuditEventAppendService(
        appender=FailingAppender(),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="audit write failed"):
        service.append(audit_command())


def test_a_file_fingerprint_is_kept_only_in_a_sha256_field() -> None:
    """V1-057 (DL-072 answer 12): an export's audit event keeps its file's SHA-256."""
    from property_rental.audit import _freeze_audit_value, is_file_fingerprint

    digest = "0123456789abcdef" * 4
    assert _freeze_audit_value({"file_sha256": digest}, "resulting_state")
    assert is_file_fingerprint(digest, "file_sha256")
    assert not is_file_fingerprint(digest.upper(), "file_sha256")
    assert not is_file_fingerprint(digest, "file_reference")
    with pytest.raises(ValueError):
        _freeze_audit_value({"file_reference": digest}, "resulting_state")
    with pytest.raises(ValueError):
        _freeze_audit_value({"file_sha256": digest + "00"}, "resulting_state")


def test_stored_capability_lists_and_odd_filters_read_back_on_the_history_page() -> None:
    """Review round 1: role bundle events keep capability lists; search filters stay readable."""
    from property_rental.audit import public_audit_filters
    from property_rental.audit_api import _freeze_loaded

    assert _freeze_loaded({"version": 3, "added_capability_ids": ["audit.view", "data.export"]})
    assert _freeze_loaded({"capability_ids": ["reports.read"]})
    assert _freeze_loaded({"created_period_ids": [str(uuid4())]})
    assert _freeze_loaded({"capability": "invoices.issue", "also": "utility.calculate"})
    with pytest.raises(ValueError):
        _freeze_loaded({"added_capability_ids": ["not a capability"]})
    kept = public_audit_filters({"action": "foo bar", "resource_type": "unit", "to_date": None})
    assert kept == {"resource_type": "unit", "filters_not_recorded_count": 1}
    assert _freeze_loaded({"filters": kept})


def test_a_malformed_grant_is_refused_before_the_audit_search_reads() -> None:
    """Review round 3: a grant with a wrong Property id gives 403, not a server error."""
    from property_rental.audit_api import (
        AuditPageRequest,
        AuditQueryForbidden,
        PostgresAuditEventQueryFlow,
        PropertyAuditQuery,
    )
    from property_rental.identity import AuthenticatedActor, CapabilityGrant

    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()),
        frozenset(
            {
                CapabilityGrant("audit.view", frozenset({str(prop)})),
                CapabilityGrant("units.read", frozenset({"not-a-property"})),
            }
        ),
    )
    flow = PostgresAuditEventQueryFlow("postgresql://unused.invalid/none")
    with pytest.raises(AuditQueryForbidden):
        flow.search_property(
            actor, PropertyAuditQuery(property_id=prop, page=AuditPageRequest(limit=1))
        )
