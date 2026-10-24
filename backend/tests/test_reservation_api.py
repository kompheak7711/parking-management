"""API-032 through API-034 Reservation HTTP contract tests."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    ReservationCancelCommand,
    ReservationCreateCommand,
    ReservationExtendCommand,
    ReservationStatus,
)
from property_rental.reservation_api import (
    PostgresReservationResourceFlow,
    ReservationExtensionNotice,
    ReservationPage,
    ReservationResource,
    ReservationResourceNotFound,
)
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositCorrectionDraftCommand,
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
    ReservationDepositDecisionPage,
    ReservationDepositDraftKeyReused,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def resource(
    property_id: UUID,
    *,
    status: ReservationStatus = ReservationStatus.ACTIVE,
) -> ReservationResource:
    return ReservationResource(
        uuid4(),
        property_id,
        uuid4(),
        "101",
        uuid4(),
        "Customer One",
        date(2026, 8, 26),
        date(2026, 9, 5),
        date(2026, 9, 5),
        50_000,
        status,
        1,
        uuid4(),
        50_000,
        10_000,
        DepositOutcomeState.PENDING_V1_031,
        None,
        None,
        None,
        None,
        True,
    )


@dataclass(slots=True)
class InMemoryReservationFlow:
    resources: dict[UUID, ReservationResource] = field(default_factory=dict)
    create_command: ReservationCreateCommand | None = None
    extend_command: ReservationExtendCommand | None = None
    cancel_command: ReservationCancelCommand | None = None
    draft_calls: list[tuple[str, UUID, object, object]] = field(default_factory=list)
    awaiting_page: ReservationDepositDecisionPage | None = None

    def list(
        self,
        property_id: UUID,
        *,
        reservation_status: ReservationStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ReservationPage:
        del cursor
        items = tuple(
            item
            for item in self.resources.values()
            if item.property_id == property_id
            and (reservation_status is None or item.status is reservation_status)
        )
        return ReservationPage(items[:limit], None)

    def get(self, reservation_id: UUID) -> ReservationResource:
        try:
            return self.resources[reservation_id]
        except KeyError as exc:
            raise ReservationResourceNotFound from exc

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.create_command = command
        value = ReservationResource(
            command.reservation_id,
            property_id,
            command.unit_id,
            "101",
            command.customer_id,
            "Customer One",
            command.reservation_date,
            command.original_expiration_date,
            command.original_expiration_date,
            command.agreed_monthly_rent_usd_cents,
            ReservationStatus.ACTIVE,
            1,
            command.deposit_id,
            command.required_deposit_usd_cents,
            command.accepted_required_amount_usd_cents,
            DepositOutcomeState.PENDING_V1_031,
            None,
            None,
            None,
            None,
            True,
        )
        self.resources[value.reservation_id] = value
        return value

    def extend(
        self,
        command: ReservationExtendCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.extend_command = command
        current = self.get(command.reservation_id)
        updated = replace(
            current,
            effective_expiration_date=command.new_expiration_date,
            version=current.version + 1,
            extension_notice=ReservationExtensionNotice(
                command.notice_id,
                current.effective_expiration_date,
                command.new_expiration_date,
                # The database stamps its own time when the route sends none (sub-slice 10i-3).
                command.approved_at or datetime(2026, 9, 1, 1, tzinfo=UTC),
                command.reason_memo or None,
            ),
        )
        self.resources[updated.reservation_id] = updated
        return updated

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.cancel_command = command
        current = self.get(command.reservation_id)
        updated = replace(
            current,
            status=ReservationStatus.CANCELLED,
            version=current.version + 1,
            cancellation_reason_code=command.reason_code,
            cancellation_responsibility=command.responsibility,
            deposit_outcome_state=DepositOutcomeState.AWAITING_DECISION,
        )
        self.resources[updated.reservation_id] = updated
        return updated

    def property_for_security_deposit_disposition(self, reservation_id: UUID) -> UUID:
        return self.get(reservation_id).property_id

    def record_deposit_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        self.draft_calls.append(("record", property_id, decision, command))
        return {"draft_id": str(uuid4()), "kind": decision.value, "state": "PENDING"}

    def record_deposit_correction_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositCorrectionDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        self.draft_calls.append(("correct", property_id, decision, command))
        return {"draft_id": str(uuid4()), "kind": decision.value, "state": "PENDING"}

    def confirm_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        self.draft_calls.append(("confirm", property_id, reservation_id, draft_id))
        return {"draft": {"draft_id": str(draft_id), "state": "CONFIRMED"}, "reservation": {}}

    def decide_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        withdraw_as: ReservationDepositDecision | None,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor, reason
        self.draft_calls.append(
            ("reject" if withdraw_as is None else "withdraw", property_id, reservation_id, draft_id)
        )
        return {
            "draft_id": str(draft_id),
            "state": "REJECTED" if withdraw_as is None else "WITHDRAWN",
        }

    def awaiting_deposit_decisions(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: ReservationDepositDecisionPage,
    ) -> dict[str, object]:
        del actor
        self.awaiting_page = page
        items = [
            {"reservation_id": str(item.reservation_id)}
            for item in self.resources.values()
            if item.property_id == property_id and item.status is ReservationStatus.CANCELLED
        ]
        return {
            "items": items[: page.limit],
            "next_after": (
                {
                    "cancelled_at": "2026-08-27T01:02:03.000004+00:00",
                    "reservation_id": items[page.limit - 1]["reservation_id"],
                }
                if len(items) > page.limit
                else None
            ),
        }


def headers(*, version: int | None = None) -> dict[str, str]:
    result = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    if version is not None:
        result["If-Match"] = f'"{version}"'
    return result


def client(flow: InMemoryReservationFlow, authenticated: AuthenticatedActor) -> TestClient:
    value = TestClient(
        create_app(actor_resolver=lambda _: authenticated, reservation_resource_flow=flow)
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def test_list_is_bounded_status_filtered_private_and_capability_sensitive() -> None:
    property_id = uuid4()
    active = resource(property_id)
    cancelled = replace(resource(property_id), status=ReservationStatus.CANCELLED)
    flow = InMemoryReservationFlow(
        {active.reservation_id: active, cancelled.reservation_id: cancelled}
    )
    response = client(flow, actor(property_id, "reservations.read", "reservations.create")).get(
        f"/properties/{property_id}/reservations?status=ACTIVE&limit=1"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"]["can_create"] is True
    assert [item["status"] for item in response.json()["data"]["items"]] == ["ACTIVE"]


def test_object_scope_is_not_disclosed_to_an_actor_from_another_property() -> None:
    property_id = uuid4()
    value = resource(property_id)
    flow = InMemoryReservationFlow({value.reservation_id: value})
    response = client(flow, actor(uuid4(), "reservations.read")).get(
        f"/reservations/{value.reservation_id}"
    )

    assert response.status_code == 404


def test_create_requires_csrf_and_preserves_client_idempotent_identity_and_trace() -> None:
    property_id = uuid4()
    authenticated = actor(property_id, "reservations.read", "reservations.create")
    flow = InMemoryReservationFlow()
    reservation_id = uuid4()
    payload = {
        "reservation_id": str(reservation_id),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-08-26",
        "agreed_monthly_rent_usd_cents": 50000,
        "expiration_date": "2026-09-05",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 10000,
        "required_security_deposit_usd_cents": 50000,
        "acceptance_reason": "Accepted normal suggestion",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
    }
    api = client(flow, authenticated)
    rejected = api.post(
        f"/properties/{property_id}/reservations",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    accepted = api.post(
        f"/properties/{property_id}/reservations",
        json=payload,
        headers=headers(),
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 201
    assert accepted.headers["location"] == f"/reservations/{reservation_id}"
    assert flow.create_command is not None
    assert flow.create_command.calculation_trace["suggested_amount_usd_cents"] == 10000
    assert flow.create_command.acceptance_kind == "NORMAL_SUGGESTION"


def test_create_route_takes_no_receipt_time_from_the_request() -> None:
    """Owner answer (a) to Q-2026-10-20-147 (V1-056 sub-slice 10i-4b): the holding deposit's
    receipt and acceptance times are the moment staff save the Reservation, so the route sends no
    time to the flow and the database takes its own; a body that still sends one is refused (422)
    and the flow is not called. The money's own receipt time stays on the Payment."""
    property_id = uuid4()
    flow = InMemoryReservationFlow()
    api = client(flow, actor(property_id, "reservations.read", "reservations.create"))
    path = f"/properties/{property_id}/reservations"
    payload = {
        "reservation_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-08-26",
        "agreed_monthly_rent_usd_cents": 50000,
        "expiration_date": "2026-09-05",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 10000,
        "required_security_deposit_usd_cents": 50000,
        "acceptance_reason": "Accepted normal suggestion",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
    }

    refused = api.post(
        path, json={**payload, "received_at": "2026-08-26T01:00:00Z"}, headers=headers()
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["fields"] == ["body.received_at"]
    assert [flow.create_command] == [None]

    accepted = api.post(path, json=payload, headers=headers())

    assert accepted.status_code == 201, accepted.text
    assert flow.create_command is not None
    assert (flow.create_command.accepted_at, flow.create_command.received_at) == (None, None)


def test_authorized_variance_requires_separate_capability() -> None:
    property_id = uuid4()
    payload = {
        "reservation_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-08-26",
        "agreed_monthly_rent_usd_cents": 50000,
        "expiration_date": "2026-09-05",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 9000,
        "required_security_deposit_usd_cents": 50000,
        "acceptance_reason": "Approved variance",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
    }
    missing = client(InMemoryReservationFlow(), actor(property_id, "reservations.create")).post(
        f"/properties/{property_id}/reservations", json=payload, headers=headers()
    )
    permitted_flow = InMemoryReservationFlow()
    permitted = client(
        permitted_flow,
        actor(property_id, "reservations.create", "reservation_deposits.override"),
    ).post(f"/properties/{property_id}/reservations", json=payload, headers=headers())

    assert missing.status_code == 404
    assert permitted.status_code == 201
    assert permitted_flow.create_command is not None
    assert permitted_flow.create_command.acceptance_kind == "AUTHORIZED_VARIANCE"


def test_extend_requires_version_and_records_one_notice_shape() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(flow, actor(property_id, "reservations.read", "reservations.extend"))
    payload = {
        "notice_id": str(uuid4()),
        "new_expiration_date": "2026-09-12",
        "reason_memo": "Approved extension",
    }
    missing = api.post(
        f"/reservations/{current.reservation_id}/extend", json=payload, headers=headers()
    )
    accepted = api.post(
        f"/reservations/{current.reservation_id}/extend",
        json=payload,
        headers=headers(version=1),
    )

    assert missing.status_code == 428
    assert accepted.status_code == 200
    assert flow.extend_command is not None
    assert flow.extend_command.authorization_reference == "reservations.extend"
    assert accepted.json()["data"]["extension_notice"]["new_expiration_date"] == "2026-09-12"


def test_extend_route_takes_no_approval_time_from_the_request() -> None:
    """Owner answer (a) to Q-2026-10-14-112 point 1 (V1-056 sub-slice 10i-3): the extension
    approval time means the moment the authorized staff member records it, so the route sends no
    time to the flow and the database takes its own; a body that still sends one is refused (422)
    and the flow is not called."""
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(flow, actor(property_id, "reservations.read", "reservations.extend"))
    path = f"/reservations/{current.reservation_id}/extend"
    payload = {
        "notice_id": str(uuid4()),
        "new_expiration_date": "2026-09-12",
        "reason_memo": "Approved extension",
    }

    refused = api.post(
        path,
        json={**payload, "approved_at": "2026-09-01T01:00:00Z"},
        headers=headers(version=1),
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["fields"] == ["body.approved_at"]
    assert [flow.extend_command] == [None]

    accepted = api.post(path, json=payload, headers=headers(version=1))

    assert accepted.status_code == 200, accepted.text
    assert flow.extend_command is not None
    assert flow.extend_command.approved_at is None


def test_cancel_derives_customer_deposit_disposition_without_free_form_outcome() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(
            property_id,
            "reservations.read",
            "reservations.cancel",
            "reservation_deposits.dispose",
        ),
    )
    response = api.post(
        f"/reservations/{current.reservation_id}/cancel",
        headers=headers(version=1),
        json={
            "event_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "Cookie" in response.headers["vary"]
    assert flow.cancel_command is not None
    # V1-056 slice 3b: cancellation releases the Unit; the Deposit waits for a confirmed draft.
    assert flow.cancel_command.authorization_reference == "reservations.cancel"
    assert response.json()["data"]["deposit_outcome_state"] == "AWAITING_DECISION"


def test_explicit_security_deposit_disposition_route_reuses_atomic_cancellation() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.cancel", "reservation_deposits.dispose"),
    )
    response = api.post(
        f"/api/v1/reservations/{current.reservation_id}/security-deposit-dispositions",
        headers=headers(version=1),
        json={
            "event_id": str(uuid4()),
            "outcome_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
            "refund_number": None,
        },
    )
    # V1-056 slice 3b: the earlier atomic route records nothing; the outcome is a draft.
    assert response.status_code == 409
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["error"]["code"] == "RESERVATION_DEPOSIT_DRAFT_REQUIRED"
    assert flow.cancel_command is None
    assert flow.get(current.reservation_id).status is ReservationStatus.ACTIVE


def test_postgres_security_disposition_route_is_time_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # V1-056 slice 3b: the Reservation Deposit write is now the draft record; it keeps the
    # same connect, lock and statement time bounds on the financial connection.
    property_id = uuid4()
    actor_id = uuid4()
    reservation_id = uuid4()
    draft = {"draft_id": str(uuid4()), "state": "PENDING"}
    connect_options: list[dict[str, object]] = []
    statements: list[tuple[str, tuple[object, ...]]] = []
    urls: list[str] = []

    class Result:
        def __init__(self, row: tuple[object, ...]) -> None:
            self.row = row

        def fetchone(self) -> tuple[object, ...]:
            return self.row

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Result:
            normalized = " ".join(statement.split())
            statements.append((normalized, parameters))
            if "record_reservation_deposit_draft" in normalized:
                return Result((draft,))
            return Result((None,))

    def connect(url: str, **options: object) -> Connection:
        urls.append(url)
        connect_options.append(options)
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    flow = PostgresReservationResourceFlow("postgresql://runtime", "postgresql://financial")
    authenticated = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("reservation_deposits.dispose", frozenset({str(property_id)}))}
        ),
    )
    result = flow.record_deposit_draft(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Customer request"),
        actor=authenticated,
    )

    assert result == draft
    assert urls == ["postgresql://financial"]
    assert connect_options == [{"connect_timeout": 3}]
    assert [parameters for statement, parameters in statements if "lock_timeout" in statement] == [
        ("3000",),
    ]
    assert [
        parameters for statement, parameters in statements if "statement_timeout" in statement
    ] == [("3000",)]


def test_explicit_security_deposit_disposition_requires_precondition_without_caching() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.cancel", "reservation_deposits.dispose"),
    )
    response = api.post(
        f"/api/v1/reservations/{current.reservation_id}/security-deposit-dispositions",
        headers=headers(),
        json={
            "event_id": str(uuid4()),
            "outcome_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
            "refund_number": None,
        },
    )

    # V1-056 slice 3b: the retired route answers 409 before any precondition check.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESERVATION_DEPOSIT_DRAFT_REQUIRED"
    assert response.headers["cache-control"] == "private, no-store"
    assert "Cookie" in response.headers["vary"]
    assert flow.cancel_command is None


def test_no_generic_status_patch_and_move_in_requires_v1_036_command_schema() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.read", "reservations.complete"),
    )

    patch_response = api.patch(
        f"/reservations/{current.reservation_id}", json={"status": "CANCELLED"}
    )
    assert patch_response.status_code == 405
    assert api.post(f"/reservations/{current.reservation_id}/complete-move-in").status_code == 404


def cancelled(property_id: UUID, responsibility: CancellationResponsibility) -> ReservationResource:
    return replace(
        resource(property_id),
        status=ReservationStatus.CANCELLED,
        version=2,
        cancellation_reason_code="CUSTOMER_WITHDREW"
        if responsibility is CancellationResponsibility.CUSTOMER
        else "PROPERTY_UNABLE_TO_PROVIDE_UNIT",
        cancellation_responsibility=responsibility,
        deposit_outcome_state=DepositOutcomeState.AWAITING_DECISION,
    )


def test_deposit_draft_kind_and_capability_follow_cancellation_responsibility() -> None:
    property_id = uuid4()
    customer = cancelled(property_id, CancellationResponsibility.CUSTOMER)
    refund = cancelled(property_id, CancellationResponsibility.PROPERTY)
    flow = InMemoryReservationFlow(
        {customer.reservation_id: customer, refund.reservation_id: refund}
    )
    forfeiture_only = client(
        flow, actor(property_id, "reservations.read", "reservation_deposits.dispose")
    )
    method_id = uuid4()

    forfeiture = forfeiture_only.post(
        f"/reservations/{customer.reservation_id}/deposit-drafts",
        json={"outcome_id": str(uuid4()), "reason": "Customer withdrew"},
        headers=headers(),
    )
    refund_denied = forfeiture_only.post(
        f"/reservations/{refund.reservation_id}/deposit-drafts",
        json={
            "outcome_id": str(uuid4()),
            "reason": "Property could not provide the Unit",
            "refund_method_id": str(method_id),
            "reference_note": "Cash at the office",
        },
        headers=headers(),
    )
    refund_allowed = client(
        flow, actor(property_id, "reservations.read", "reservation_deposits.refund")
    ).post(
        f"/reservations/{refund.reservation_id}/deposit-drafts",
        json={
            "outcome_id": str(uuid4()),
            "reason": "Property could not provide the Unit",
            "refund_method_id": str(method_id),
            "reference_note": "Cash at the office",
        },
        headers=headers(),
    )

    # DL-071 answer 10 (V1-059 part B): staff no longer type a Refund number.
    typed_number = client(
        flow, actor(property_id, "reservations.read", "reservation_deposits.refund")
    ).post(
        f"/reservations/{refund.reservation_id}/deposit-drafts",
        json={
            "outcome_id": str(uuid4()),
            "reason": "Property could not provide the Unit",
            "refund_number": "RF-1",
            "refund_method_id": str(method_id),
            "reference_note": "Cash at the office",
        },
        headers=headers(),
    )

    assert forfeiture.status_code == 201
    assert forfeiture.headers["cache-control"] == "private, no-store"
    assert refund_denied.status_code == 404
    assert refund_allowed.status_code == 201
    assert typed_number.status_code == 422
    kinds = [call[2] for call in flow.draft_calls]
    assert kinds == [
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        ReservationDepositDecision.REFUND,
    ]
    refund_command = flow.draft_calls[1][3]
    assert isinstance(refund_command, RecordReservationDepositDraftCommand)
    assert refund_command.method is not None
    assert refund_command.method.refund_method_id == method_id


def test_deposit_draft_routes_refuse_active_reservations_csrf_and_partial_method() -> None:
    property_id = uuid4()
    active = resource(property_id)
    refund = cancelled(property_id, CancellationResponsibility.PROPERTY)
    flow = InMemoryReservationFlow({active.reservation_id: active, refund.reservation_id: refund})
    api = client(
        flow,
        actor(
            property_id,
            "reservations.read",
            "reservation_deposits.dispose",
            "reservation_deposits.refund",
        ),
    )
    not_cancelled = api.post(
        f"/reservations/{active.reservation_id}/deposit-drafts",
        json={"outcome_id": str(uuid4()), "reason": "Too early"},
        headers=headers(),
    )
    no_csrf = api.post(
        f"/reservations/{refund.reservation_id}/deposit-drafts",
        json={"outcome_id": str(uuid4()), "reason": "No token"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    partial_method = api.post(
        f"/reservations/{refund.reservation_id}/deposit-drafts",
        json={
            "outcome_id": str(uuid4()),
            "reason": "Method without note",
            "refund_method_id": str(uuid4()),
        },
        headers=headers(),
    )

    assert not_cancelled.status_code == 422
    assert no_csrf.status_code == 403
    assert partial_method.status_code == 422
    assert flow.draft_calls == []


def test_only_financial_approve_confirms_a_reservation_deposit_draft() -> None:
    property_id = uuid4()
    customer = cancelled(property_id, CancellationResponsibility.CUSTOMER)
    flow = InMemoryReservationFlow({customer.reservation_id: customer})
    draft_id = uuid4()
    path = f"/reservations/{customer.reservation_id}/deposit-drafts/{draft_id}/confirm"

    staff = client(
        flow,
        actor(
            property_id,
            "reservations.read",
            "reservation_deposits.dispose",
            "reservation_deposits.correct",
        ),
    ).post(path, headers=headers())
    approver = client(flow, actor(property_id, "reservations.read", "financial.approve"))
    no_csrf = approver.post(path, headers={"Idempotency-Key": str(uuid4())})
    confirmed = approver.post(path, headers=headers())

    assert staff.status_code == 404
    assert no_csrf.status_code == 403
    assert confirmed.status_code == 200
    assert confirmed.headers["cache-control"] == "private, no-store"
    assert flow.draft_calls == [("confirm", property_id, customer.reservation_id, draft_id)]


def test_correction_draft_needs_the_correct_capability_and_the_kind_capability() -> None:
    property_id = uuid4()
    customer = cancelled(property_id, CancellationResponsibility.CUSTOMER)
    flow = InMemoryReservationFlow({customer.reservation_id: customer})
    body = {
        "expected_outcome_id": str(uuid4()),
        "correction_id": str(uuid4()),
        "replacement_outcome_id": str(uuid4()),
        "reason": "Correct evidence",
        "evidence_reference": "CASE-1",
    }
    path = f"/reservations/{customer.reservation_id}/deposit-correction-drafts"

    without_correct = client(
        flow, actor(property_id, "reservations.read", "reservation_deposits.dispose")
    ).post(path, json=body, headers=headers())
    without_kind = client(
        flow, actor(property_id, "reservations.read", "reservation_deposits.correct")
    ).post(path, json=body, headers=headers())
    allowed = client(
        flow,
        actor(
            property_id,
            "reservations.read",
            "reservation_deposits.correct",
            "reservation_deposits.dispose",
        ),
    ).post(path, json=body, headers=headers())

    assert without_correct.status_code == 404
    assert without_kind.status_code == 404
    assert allowed.status_code == 201
    assert [call[0] for call in flow.draft_calls] == ["correct"]
    assert flow.draft_calls[0][2] is ReservationDepositDecision.DEPOSIT_FORFEITURE


def test_waiting_list_is_bounded_private_paged_and_read_capability_scoped() -> None:
    property_id = uuid4()
    first = cancelled(property_id, CancellationResponsibility.CUSTOMER)
    second = cancelled(property_id, CancellationResponsibility.PROPERTY)
    flow = InMemoryReservationFlow({first.reservation_id: first, second.reservation_id: second})
    path = f"/properties/{property_id}/reservation-deposit-decisions"

    denied = client(flow, actor(property_id, "reservation_deposits.dispose")).get(path)
    reader = client(flow, actor(property_id, "reservations.read"))
    too_large = reader.get(path + "?limit=101")
    bad_cursor = reader.get(path + "?cursor=not-a-cursor")
    page = reader.get(path + "?limit=1")
    cursor = page.json()["data"]["next_cursor"]
    following = reader.get(path, params={"limit": 1, "cursor": cursor})

    assert denied.status_code == 404
    assert too_large.status_code == 422
    assert bad_cursor.status_code == 422
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert len(page.json()["data"]["items"]) == 1
    assert isinstance(cursor, str)
    assert following.status_code == 200
    assert flow.awaiting_page is not None
    assert flow.awaiting_page.after_id == UUID(page.json()["data"]["items"][0]["reservation_id"])
    assert flow.awaiting_page.after_cancelled_at is not None


def test_reused_draft_key_answers_idempotency_key_reused() -> None:
    property_id = uuid4()
    customer = cancelled(property_id, CancellationResponsibility.CUSTOMER)

    class ReusedFlow(InMemoryReservationFlow):
        def record_deposit_draft(
            self,
            property_id: UUID,
            decision: ReservationDepositDecision,
            command: RecordReservationDepositDraftCommand,
            *,
            actor: AuthenticatedActor,
        ) -> dict[str, object]:
            del property_id, decision, command, actor
            raise ReservationDepositDraftKeyReused("Reservation Deposit draft key was reused")

    response = client(
        ReusedFlow({customer.reservation_id: customer}),
        actor(property_id, "reservations.read", "reservation_deposits.dispose"),
    ).post(
        f"/reservations/{customer.reservation_id}/deposit-drafts",
        json={"outcome_id": str(uuid4()), "reason": "Changed reason"},
        headers=headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert response.json()["error"]["rule_ids"] == ["API-016"]


def test_reject_needs_financial_approve_and_withdraw_needs_the_kind_capability() -> None:
    property_id = uuid4()
    customer = cancelled(property_id, CancellationResponsibility.CUSTOMER)
    flow = InMemoryReservationFlow({customer.reservation_id: customer})
    draft_id = uuid4()
    base = f"/reservations/{customer.reservation_id}/deposit-drafts/{draft_id}"
    body = {"reason": "Wrong reason text"}
    staff = client(flow, actor(property_id, "reservations.read", "reservation_deposits.dispose"))
    approver = client(flow, actor(property_id, "reservations.read", "financial.approve"))

    staff_reject = staff.post(base + "/reject", json=body, headers=headers())
    approver_withdraw = approver.post(base + "/withdraw", json=body, headers=headers())
    no_reason = approver.post(base + "/reject", json={}, headers=headers())
    no_csrf = approver.post(base + "/reject", json=body, headers={"Idempotency-Key": str(uuid4())})
    rejected = approver.post(base + "/reject", json=body, headers=headers())
    withdrawn = staff.post(base + "/withdraw", json=body, headers=headers())

    assert staff_reject.status_code == 404
    assert approver_withdraw.status_code == 404
    assert no_reason.status_code == 422
    assert no_csrf.status_code == 403
    assert rejected.status_code == 200
    assert rejected.headers["cache-control"] == "private, no-store"
    assert withdrawn.status_code == 200
    assert flow.draft_calls == [
        ("reject", property_id, customer.reservation_id, draft_id),
        ("withdraw", property_id, customer.reservation_id, draft_id),
    ]
