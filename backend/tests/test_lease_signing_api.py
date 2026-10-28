"""HTTP boundary of the signing routes (V1-060 B6, DL-100; B7, DL-108) with an in-memory flow."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.pq import DiagnosticField

from property_rental.api_refusals import RefusedRequest
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_signing_api import (
    SIGN_REFUSALS,
    LeaseSigningConflict,
    LeaseSigningNotFound,
    LeaseSigningUnavailable,
    SignWithPaymentCommand,
    _sign_error,
    sign_with_payment_digest,
)
from test_invoice import mutation_headers

PROPERTY = uuid4()
HELD = {"deposit_id": str(UUID(int=9)), "required_usd_cents": 50_000, "received_usd_cents": 10_000}
SIGNED: dict[str, object] = {"lease_id": str(UUID(int=1)), "lease_version": 4, "payment_id": "p"}
MONEY = ("leases.sign", "payments.record", "payments.allocate")


class MemoryFlow:
    def __init__(self) -> None:
        self.plans: list[tuple[UUID, UUID, UUID, UUID, int, str]] = []
        self.signed: list[tuple[UUID, UUID, SignWithPaymentCommand, UUID, bool]] = []
        self.failure: Exception | None = None

    def property_of(self, lease_id: UUID) -> UUID:
        if self.failure is not None and isinstance(self.failure, LeaseSigningNotFound):
            raise self.failure
        return PROPERTY

    def preview(self, property_id: UUID, lease_id: UUID) -> dict[str, object]:
        return {
            "initial": None,
            "planned_security_deposit_usd_cents": 50_000,
            "held_security_deposit": HELD,
        }

    def set_planned_deposit(
        self,
        property_id: UUID,
        lease_id: UUID,
        plan_id: UUID,
        actor_id: UUID,
        required_usd_cents: int,
        reason: str,
    ) -> int:
        self.plans.append((property_id, lease_id, plan_id, actor_id, required_usd_cents, reason))
        return required_usd_cents

    def sign_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: SignWithPaymentCommand,
        actor_id: UUID,
        may_create_deposit: bool,
    ) -> dict[str, object]:
        if self.failure is not None:
            raise self.failure
        self.signed.append((property_id, lease_id, command, actor_id, may_create_deposit))
        return SIGNED


def client(flow: MemoryFlow, *capabilities: str) -> tuple[TestClient, UUID]:
    actor = uuid4()
    who = AuthenticatedActor(
        actor_id=str(actor),
        capability_grants=frozenset(
            CapabilityGrant(name, frozenset({str(PROPERTY)})) for name in capabilities
        ),
    )
    app = create_app(actor_resolver=lambda _: who, lease_signing_flow=flow)
    test_client = TestClient(app)
    test_client.cookies.set("__Host-prm_csrf", "csrf")
    return test_client, actor


def test_the_signing_preview_needs_lease_read() -> None:
    flow = MemoryFlow()
    lease = uuid4()
    http, _ = client(flow, "leases.read")
    reply = http.get(f"/api/v1/leases/{lease}/signing-preview")
    assert reply.status_code == 200
    assert reply.json()["data"]["planned_security_deposit_usd_cents"] == 50_000
    assert reply.headers["Cache-Control"] == "private, no-store"
    assert http.get(f"/api/v1/leases/{lease}/signing-preview?x=1").status_code == 400
    nobody, _ = client(flow)
    assert nobody.get(f"/api/v1/leases/{lease}/signing-preview").status_code == 404


def test_the_planned_security_deposit_is_saved_with_lease_draft_only() -> None:
    flow = MemoryFlow()
    lease, plan = uuid4(), uuid4()
    http, actor = client(flow, "leases.draft")
    body = {"plan_id": str(plan), "required_usd_cents": 60_000, "reason": "Draft Lease terms"}
    reply = http.put(
        f"/api/v1/leases/{lease}/planned-security-deposit", json=body, headers=mutation_headers()
    )
    assert reply.status_code == 200
    assert reply.json()["data"] == {"planned_security_deposit_usd_cents": 60_000}
    assert flow.plans == [(PROPERTY, lease, plan, actor, 60_000, "Draft Lease terms")]
    for bad in (
        {**body, "required_usd_cents": 0},
        {**body, "required_usd_cents": "600"},
        {**body, "reason": ""},
        {**body, "extra": 1},
    ):
        assert (
            http.put(
                f"/api/v1/leases/{lease}/planned-security-deposit",
                json=bad,
                headers=mutation_headers(),
            ).status_code
            == 422
        )
    signer, _ = client(flow, "leases.sign")
    assert (
        signer.put(
            f"/api/v1/leases/{lease}/planned-security-deposit",
            json=body,
            headers=mutation_headers(),
        ).status_code
        == 404
    )
    assert len(flow.plans) == 1


def _signing(signers: list[str] | None = None, **payment: object) -> dict[str, object]:
    return {
        "signer_ids": signers if signers is not None else [str(UUID(int=2)), str(UUID(int=3))],
        "reason": "Every Signer signed the paper Lease",
        "payment": {
            "payment_method_id": str(UUID(int=5)),
            "received_at": "2026-10-28T03:00:00Z",
            "evidence_reference": "Cash received, Cash",
            "amount": {"currency": "USD", "minor_units": 130_000},
            **payment,
        },
    }


def test_sign_with_payment_is_one_command_at_the_lease_version_the_screen_showed() -> None:
    flow = MemoryFlow()
    lease, key = uuid4(), uuid4()
    http, actor = client(flow, *MONEY)
    path = f"/api/v1/leases/{lease}/sign-with-payment"
    reply = http.post(path, json=_signing(), headers=mutation_headers(key=key, version=3))
    assert reply.status_code == 201
    assert reply.json()["data"] == SIGNED
    assert reply.json()["meta"]["property_id"] == str(PROPERTY)
    assert reply.headers["ETag"] == '"4"'
    assert reply.headers["Cache-Control"] == "private, no-store"
    assert flow.signed == [
        (
            PROPERTY,
            lease,
            SignWithPaymentCommand(
                idempotency_key=key,
                expected_version=3,
                signer_ids=(UUID(int=2), UUID(int=3)),
                reason="Every Signer signed the paper Lease",
                payment_method_id=UUID(int=5),
                received_amount_minor=130_000,
                received_at=datetime(2026, 10, 28, 3, tzinfo=UTC),
                evidence_reference="Cash received, Cash",
                payer_intent_memo=None,
            ),
            actor,
            False,
        )
    ]
    # A walk-in Lease's Security Deposit is made only for a person who may manage deposits.
    manager, _ = client(flow, *MONEY, "deposits.manage")
    assert (
        manager.post(path, json=_signing(), headers=mutation_headers(version=3)).status_code == 201
    )
    assert flow.signed[-1][4] is True


def test_sign_with_payment_needs_every_right_and_the_lease_version() -> None:
    flow = MemoryFlow()
    lease = uuid4()
    path = f"/api/v1/leases/{lease}/sign-with-payment"
    for missing in MONEY:
        http, _ = client(flow, *(name for name in MONEY if name != missing))
        reply = http.post(path, json=_signing(), headers=mutation_headers(version=3))
        assert reply.status_code == 404
    http, _ = client(flow, *MONEY)
    assert http.post(path, json=_signing(), headers=mutation_headers()).status_code == 428
    for version, answer in (('"x"', 400), ('"0"', 400), ("3", 428)):
        headers = {**mutation_headers(), "If-Match": version}
        assert http.post(path, json=_signing(), headers=headers).status_code == answer
    nil = mutation_headers(key=UUID(int=0), version=3)
    assert http.post(path, json=_signing(), headers=nil).status_code == 400
    twice = [*mutation_headers(version=3).items(), ("If-Match", '"3"')]
    assert http.post(path, json=_signing(), headers=twice).status_code == 400
    other = {**mutation_headers(version=3), "X-Financial-Property-ID": str(uuid4())}
    assert http.post(path, json=_signing(), headers=other).status_code == 404
    no_csrf = {
        name: value for name, value in mutation_headers(version=3).items() if name != "X-CSRF-Token"
    }
    assert http.post(path, json=_signing(), headers=no_csrf).status_code == 403
    assert flow.signed == []


def test_sign_with_payment_refuses_a_bad_request_before_any_work() -> None:
    flow = MemoryFlow()
    http, _ = client(flow, *MONEY)
    path = f"/api/v1/leases/{uuid4()}/sign-with-payment"
    for bad in (
        _signing(signers=[str(UUID(int=2)), str(UUID(int=2))]),
        {**_signing(), "reason": " Signed "},
        {**_signing(), "reason": ""},
        {**_signing(), "extra": 1},
        _signing(amount={"currency": "KHR", "minor_units": 130_000}),
        _signing(amount={"currency": "USD", "minor_units": "1300"}),
        _signing(amount={"currency": "USD", "minor_units": 0}),
        _signing(evidence_reference=""),
        _signing(payer="someone else"),
    ):
        reply = http.post(path, json=bad, headers=mutation_headers(version=3))
        assert reply.status_code == 422, bad
    assert flow.signed == []


def test_sign_with_payment_answers_why_nothing_was_saved() -> None:
    flow = MemoryFlow()
    http, _ = client(flow, *MONEY)
    path = f"/api/v1/leases/{uuid4()}/sign-with-payment"
    flow.failure = RefusedRequest(SIGN_REFUSALS["The money due at signing changed"])
    refused = http.post(path, json=_signing(), headers=mutation_headers(version=3))
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "SIGNING_TOTAL_CHANGED"
    assert "Nothing was saved" in refused.json()["error"]["message"]
    flow.failure = LeaseSigningConflict()
    assert http.post(path, json=_signing(), headers=mutation_headers(version=3)).status_code == 412
    flow.failure = LeaseSigningUnavailable()
    assert http.post(path, json=_signing(), headers=mutation_headers(version=3)).status_code == 503
    flow.failure = LeaseSigningNotFound()
    assert http.post(path, json=_signing(), headers=mutation_headers(version=3)).status_code == 404


def _raised(
    sqlstate: str, message: str = "refused", constraint: str | None = None
) -> psycopg.Error:
    """An error as the database sends it: its code, its words and the check it broke."""
    info: dict[int, bytes | None] = {
        DiagnosticField.SQLSTATE: sqlstate.encode(),
        DiagnosticField.MESSAGE_PRIMARY: message.encode(),
        DiagnosticField.CONSTRAINT_NAME: None if constraint is None else constraint.encode(),
    }
    try:
        kind = psycopg.errors.lookup(sqlstate)
    except KeyError:
        kind = psycopg.DatabaseError
    return kind(message, info=info)


def test_a_failure_inside_the_command_is_a_refusal_unless_its_outcome_is_unknown() -> None:
    """V1-060 B7 (second review): the command saved nothing when it raised, so a broken rule is a
    refusal; only a deadlock, a lock wait, a timeout or a lost connection is not known (the screen
    then sends the same request again). Third review: only the signed-Lease exclusion is
    SIGNING_DATES_TAKEN, and the known words choose their own refusal."""
    refused = {
        _raised("23P01", constraint="leases_signed_period_exclusive"): "SIGNING_DATES_TAKEN",
        _raised("23P01", constraint="active_invoice_source_claims_period"): "SIGNING_REFUSED",
        _raised("23P01"): "SIGNING_REFUSED",
        _raised("23505"): "SIGNING_REFUSED",
        _raised("23514"): "SIGNING_REFUSED",
        _raised("23503"): "SIGNING_REFUSED",
        _raised("55000"): "SIGNING_REFUSED",
        _raised("P4506"): "SIGNING_REFUSED",
        _raised("P5S01"): "SIGNING_REFUSED",
        _raised("P5305", "Payment confirmation key reused"): "SIGNING_REFUSED",
        _raised("P5305", "Sign Lease key reused"): "SIGNING_KEY_REUSED",
        _raised("P5301", "Payment source not found"): "SIGNING_PAYMENT_SOURCE_GONE",
        _raised("23514", "Payment Method is not accepted"): "SIGNING_PAYMENT_SOURCE_GONE",
        _raised(
            "23514", "Reservation cannot be completed by this signing"
        ): "SIGNING_RESERVATION_ENDED",
    }
    for error, code in refused.items():
        with pytest.raises(RefusedRequest) as caught:
            _sign_error(error)
        assert caught.value.refusal.code == code, error.diag.message_primary
        message = caught.value.refusal.message
        assert "Nothing was saved" in message or "Nothing more was saved" in message
    assert _raised("P5305", "Payment confirmation key reused").sqlstate == "P5305"
    unknown: tuple[type[psycopg.Error], ...] = (
        psycopg.errors.DeadlockDetected,
        psycopg.errors.LockNotAvailable,
        psycopg.errors.QueryCanceled,
        psycopg.OperationalError,
    )
    for failure in unknown:
        with pytest.raises(LeaseSigningUnavailable):
            _sign_error(failure("not known"))
    with pytest.raises(LeaseSigningConflict):
        _sign_error(psycopg.errors.SerializationFailure("stale"))


def test_every_sign_lease_refusal_says_nothing_was_saved() -> None:
    signing_only = {
        name: refusal for name, refusal in SIGN_REFUSALS.items() if "SIGNING" in refusal.code
    }
    assert signing_only
    for refusal in signing_only.values():
        assert "Nothing was saved" in refusal.message or "Nothing more was saved" in refusal.message


def test_the_sign_lease_digest_binds_the_whole_request() -> None:
    command = SignWithPaymentCommand(
        idempotency_key=uuid4(),
        expected_version=3,
        signer_ids=(UUID(int=2), UUID(int=3)),
        reason="Signed",
        payment_method_id=UUID(int=5),
        received_amount_minor=130_000,
        received_at=datetime(2026, 10, 28, 3, tzinfo=UTC),
        evidence_reference="Cash received, Cash",
        payer_intent_memo=None,
    )
    lease = uuid4()
    digest = sign_with_payment_digest(PROPERTY, lease, command)
    assert len(digest) == 64
    # The order of the ticks does not matter; the key itself is not part of the request.
    assert digest == sign_with_payment_digest(
        PROPERTY,
        lease,
        replace(command, signer_ids=(UUID(int=3), UUID(int=2)), idempotency_key=uuid4()),
    )
    for changed in (
        replace(command, expected_version=4),
        replace(command, signer_ids=(UUID(int=2),)),
        replace(command, reason="Signed today"),
        replace(command, payment_method_id=UUID(int=6)),
        replace(command, received_amount_minor=130_001),
        replace(command, received_at=datetime(2026, 10, 28, 3, 0, 1, tzinfo=UTC)),
        replace(command, evidence_reference="Bank transfer"),
        replace(command, payer_intent_memo="Rent and deposit"),
    ):
        assert sign_with_payment_digest(PROPERTY, lease, changed) != digest
    assert sign_with_payment_digest(uuid4(), lease, command) != digest
    assert sign_with_payment_digest(PROPERTY, uuid4(), command) != digest


def test_the_reservation_deposit_in_the_preview_needs_deposit_or_booking_read() -> None:
    flow = MemoryFlow()
    lease = uuid4()
    reader, _ = client(flow, "leases.read")
    reply = reader.get(f"/api/v1/leases/{lease}/signing-preview")
    assert reply.status_code == 200
    # The draft's own amount is a Lease term; the money received belongs to the deposit.
    assert reply.json()["data"]["planned_security_deposit_usd_cents"] == 50_000
    assert reply.json()["data"]["held_security_deposit"] is None
    for allowed in ("deposits.read", "reservations.read"):
        http, _ = client(flow, "leases.read", allowed)
        assert (
            http.get(f"/api/v1/leases/{lease}/signing-preview").json()["data"][
                "held_security_deposit"
            ]
            == HELD
        )
