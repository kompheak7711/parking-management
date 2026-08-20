"""Focused tests for recovery-code, administrative, and emergency orchestration."""

from dataclasses import fields, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from property_rental.account_recovery import (
    AccountRecoveryAuditEvidence,
    AccountRecoveryFailed,
    AccountRecoveryMutation,
    AccountRecoveryRateLimited,
    AccountRecoveryRejected,
    AccountRecoveryRequest,
    AccountRecoveryResult,
    AccountRecoveryService,
    PostgresAccountRecoveryRepository,
    TrustedAccountRecoveryAuthorizer,
)
from property_rental.administrative_recovery import (
    AdministrativeRecoveryAuthorizationService,
    RecoveryAccount,
    RecoveryAuthorizationAuditEvidence,
)
from property_rental.password_security import PasswordCredentialMaterial

OCCURRED_AT = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


class RecordingLimiter:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.keys: list[tuple[str, str]] = []

    def allow(self, account_key: str, source_key: str) -> bool:
        self.keys.append((account_key, source_key))
        return self.allowed


class RecordingAuthorizer:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.requests: list[AccountRecoveryRequest] = []

    def authorize(self, request: AccountRecoveryRequest) -> bool:
        self.requests.append(request)
        return self.allowed


class FailingAuthorizer(RecordingAuthorizer):
    def authorize(self, request: AccountRecoveryRequest) -> bool:
        del request
        raise RuntimeError("authorization provider detail")


class RecordingRepository:
    def __init__(self, result: AccountRecoveryResult | None = None) -> None:
        self.result = result or AccountRecoveryResult(
            completed=True,
            password_changed=True,
            mfa_disabled=False,
            recovery_code_consumed=False,
            sessions_revoked=2,
        )
        self.calls: list[tuple[AccountRecoveryRequest, AccountRecoveryMutation, str | None]] = []
        self.rejections: list[AccountRecoveryAuditEvidence] = []

    def recover_atomically(
        self,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> AccountRecoveryResult:
        self.calls.append((request, mutation, recovery_code))
        return self.result

    def record_rejection(self, evidence: AccountRecoveryAuditEvidence) -> None:
        self.rejections.append(evidence)


class FailingRepository(RecordingRepository):
    def recover_atomically(
        self,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> AccountRecoveryResult:
        del request, mutation, recovery_code
        raise RuntimeError("database provider detail")


class RejectingRepository(RecordingRepository):
    def recover_atomically(
        self,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> AccountRecoveryResult:
        del request, mutation, recovery_code
        raise AccountRecoveryRejected("account recovery rejected")


class FailingRejectionRepository(RecordingRepository):
    def record_rejection(self, evidence: AccountRecoveryAuditEvidence) -> None:
        del evidence
        raise RuntimeError("immutable audit unavailable")


class StubRecoveryCodeVerifier:
    def matches(self, candidate: str, verifier_encoding: str) -> bool:
        return candidate == "valid-code" and verifier_encoding == "$argon2id$valid"


class RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 1
        self.recovery_rows: list[tuple[object, ...]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))
        self.rowcount = 2 if "UPDATE app.browser_sessions" in query else 1

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.recovery_rows

    def fetchone(self) -> tuple[object, ...] | None:
        if not self.executions or "app.perform_account_recovery" not in self.executions[-1][0]:
            return None
        parameters = self.executions[-1][1]
        return (parameters[6] is not None, bool(parameters[9]), parameters[10] is not None, 2)


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor | None = None) -> None:
        self.cursor_instance = cursor or RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def password_mutation() -> AccountRecoveryMutation:
    return AccountRecoveryMutation(
        password_credential=PasswordCredentialMaterial(
            verifier_encoding="$argon2id$v=19$opaque",
            algorithm="argon2id",
            work_factor_metadata={"time_cost": 3},
        )
    )


def administrative_request(
    *,
    actor_class: str = "owner",
    target_class: str = "manager",
) -> AccountRecoveryRequest:
    return AccountRecoveryRequest(
        mode="administrative",
        actor_id=UUID(int=1),
        target_actor_id=UUID(int=2),
        actor_class=actor_class,
        target_class=target_class,
        request_source="trusted-admin-source",
        correlation_id=UUID(int=3),
        reason="authorized_account_recovery",
        authorization_proof_identity="password-preauthorization-3",
    )


def make_service(
    *,
    limiter: RecordingLimiter | None = None,
    authorizer: RecordingAuthorizer | None = None,
    repository: RecordingRepository | None = None,
) -> tuple[AccountRecoveryService, RecordingLimiter, RecordingAuthorizer, RecordingRepository]:
    selected_limiter = limiter or RecordingLimiter()
    selected_authorizer = authorizer or RecordingAuthorizer()
    selected_repository = repository or RecordingRepository()
    return (
        AccountRecoveryService(
            attempt_limiter=selected_limiter,
            authorizer=selected_authorizer,
            repository=selected_repository,
            clock=lambda: OCCURRED_AT,
        ),
        selected_limiter,
        selected_authorizer,
        selected_repository,
    )


def test_authorized_owner_administrative_recovery_applies_mutation_and_revocation_atomically() -> (
    None
):
    service, limiter, authorizer, repository = make_service()
    request = administrative_request()
    mutation = password_mutation()

    result = service.recover(request=request, mutation=mutation)

    assert result.completed
    assert result.sessions_revoked == 2
    assert limiter.keys == [(str(request.target_actor_id), request.request_source)]
    assert authorizer.requests == [request]
    assert repository.calls == [(request, mutation, None)]


@pytest.mark.parametrize(
    ("actor_class", "target_class"),
    [
        ("staff", "owner"),
        ("staff", "manager"),
        ("manager", "staff"),
        ("owner", "owner"),
    ],
)
def test_administrative_recovery_never_broadens_the_approved_matrix(
    actor_class: str,
    target_class: str,
) -> None:
    service, _, authorizer, repository = make_service(authorizer=RecordingAuthorizer(False))
    request = administrative_request(actor_class=actor_class, target_class=target_class)

    with pytest.raises(AccountRecoveryRejected, match=r"^account recovery rejected$"):
        service.recover(request=request, mutation=password_mutation())

    assert authorizer.requests == [request]
    assert repository.calls == []
    assert repository.rejections[0].reason == "authorization_denied"


def test_rate_limit_is_checked_before_authorization_or_secret_work() -> None:
    service, limiter, authorizer, repository = make_service(limiter=RecordingLimiter(False))
    request = administrative_request()

    with pytest.raises(AccountRecoveryRateLimited, match=r"^account recovery rate limited$"):
        service.recover(request=request, mutation=password_mutation())

    assert limiter.keys == [(str(request.target_actor_id), request.request_source)]
    assert authorizer.requests == []
    assert repository.calls == []
    assert repository.rejections[0].reason == "rate_limited"


def test_owner_recovery_code_path_requires_owner_self_target_and_no_credential_mutation() -> None:
    secret = "owner-recovery-code-secret"
    request = AccountRecoveryRequest(
        mode="recovery_code",
        actor_id=UUID(int=7),
        target_actor_id=UUID(int=7),
        actor_class="owner",
        target_class="owner",
        request_source="password-verified-preauth",
        correlation_id=UUID(int=8),
        reason="mfa_recovery",
    )
    repository = RecordingRepository(
        AccountRecoveryResult(
            completed=True,
            password_changed=False,
            mfa_disabled=False,
            recovery_code_consumed=True,
            sessions_revoked=1,
        )
    )
    service, _, authorizer, repository = make_service(repository=repository)

    result = service.recover(
        request=request,
        mutation=AccountRecoveryMutation(),
        recovery_code=secret,
    )

    assert result.recovery_code_consumed
    assert authorizer.requests == [request]
    assert repository.calls[0][2] == secret
    assert secret not in repr(request)
    assert secret not in repr(repository.calls[0][1])


@pytest.mark.parametrize(
    "recovery_request",
    [
        AccountRecoveryRequest(
            mode="recovery_code",
            actor_id=UUID(int=1),
            target_actor_id=UUID(int=2),
            actor_class="owner",
            target_class="owner",
            request_source="preauth",
            correlation_id=UUID(int=3),
            reason="mfa_recovery",
        ),
        AccountRecoveryRequest(
            mode="recovery_code",
            actor_id=UUID(int=1),
            target_actor_id=UUID(int=1),
            actor_class="staff",
            target_class="staff",
            request_source="preauth",
            correlation_id=UUID(int=3),
            reason="mfa_recovery",
        ),
    ],
)
def test_recovery_code_orchestration_cannot_be_used_as_an_owner_reset(
    recovery_request: AccountRecoveryRequest,
) -> None:
    service, _, authorizer, repository = make_service(authorizer=RecordingAuthorizer(False))

    with pytest.raises(AccountRecoveryRejected, match=r"^account recovery rejected$"):
        service.recover(
            request=recovery_request,
            mutation=AccountRecoveryMutation(),
            recovery_code="not-used",
        )

    expected_authorizer_requests = (
        [] if recovery_request.actor_id != recovery_request.target_actor_id else [recovery_request]
    )
    assert authorizer.requests == expected_authorizer_requests
    assert repository.calls == []


def test_emergency_owner_recovery_requires_controlled_procedure_identity() -> None:
    request = AccountRecoveryRequest(
        mode="emergency",
        actor_id=None,
        target_actor_id=UUID(int=10),
        actor_class=None,
        target_class="owner",
        request_source="production-console",
        correlation_id=UUID(int=11),
        reason="documented_emergency_recovery",
        procedure_identity="owner_recovery_v1",
    )
    service, _, authorizer, repository = make_service()

    result = service.recover(request=request, mutation=AccountRecoveryMutation(reset_mfa=True))

    assert result.completed
    assert authorizer.requests == [request]
    assert repository.calls == [(request, AccountRecoveryMutation(reset_mfa=True), None)]


def test_emergency_recovery_rejects_missing_procedure_or_non_owner_target() -> None:
    service, _, authorizer, repository = make_service(authorizer=RecordingAuthorizer(False))

    for procedure_identity, target_class in [(None, "owner"), ("controlled-procedure", "manager")]:
        request = AccountRecoveryRequest(
            mode="emergency",
            actor_id=None,
            target_actor_id=UUID(int=10),
            actor_class=None,
            target_class=target_class,
            request_source="production-console",
            correlation_id=UUID(int=11),
            reason="documented_emergency_recovery",
            procedure_identity=procedure_identity,
        )
        with pytest.raises(AccountRecoveryRejected, match=r"^account recovery rejected$"):
            service.recover(request=request, mutation=AccountRecoveryMutation(reset_mfa=True))

    assert len(authorizer.requests) == 1
    assert repository.calls == []


def test_administrative_and_emergency_paths_require_an_actual_recovery_mutation() -> None:
    service, _, authorizer, repository = make_service()

    with pytest.raises(AccountRecoveryRejected, match=r"^account recovery rejected$"):
        service.recover(request=administrative_request(), mutation=AccountRecoveryMutation())

    assert authorizer.requests == []
    assert repository.calls == []


def test_authorization_or_repository_failure_is_generic_and_secret_free() -> None:
    request = administrative_request()
    mutation = password_mutation()
    service, _, _, repository = make_service(authorizer=FailingAuthorizer())

    with pytest.raises(AccountRecoveryRejected) as denied:
        service.recover(request=request, mutation=mutation)
    assert str(denied.value) == "account recovery rejected"
    assert denied.value.__cause__ is None
    assert repository.rejections[0].reason == "authorization_unavailable"

    service, _, _, _ = make_service(repository=FailingRepository())
    with pytest.raises(AccountRecoveryFailed) as failed:
        service.recover(request=request, mutation=mutation)
    assert str(failed.value) == "account recovery failed"
    assert failed.value.__cause__ is None
    assert "database provider detail" not in repr(failed.value)


def test_invalid_recovery_code_is_outwardly_equivalent_to_authorization_denial_and_audited() -> (
    None
):
    request = AccountRecoveryRequest(
        mode="recovery_code",
        actor_id=UUID(int=7),
        target_actor_id=UUID(int=7),
        actor_class="owner",
        target_class="owner",
        request_source="password_preauth",
        correlation_id=UUID(int=8),
        reason="mfa_recovery",
    )
    service, _, _, repository = make_service(repository=RejectingRepository())

    with pytest.raises(AccountRecoveryRejected) as rejected:
        service.recover(
            request=request,
            mutation=AccountRecoveryMutation(),
            recovery_code="invalid-code",
        )

    assert str(rejected.value) == "account recovery rejected"
    assert rejected.value.__cause__ is None
    assert repository.rejections == [
        AccountRecoveryAuditEvidence.rejected(
            request=request,
            occurred_at=OCCURRED_AT,
            reason="authorization_denied",
        )
    ]


def test_rejected_recovery_fails_closed_when_immutable_audit_is_unavailable() -> None:
    service, _, _, _ = make_service(
        limiter=RecordingLimiter(False),
        repository=FailingRejectionRepository(),
    )

    with pytest.raises(AccountRecoveryFailed, match=r"^account recovery failed$"):
        service.recover(request=administrative_request(), mutation=password_mutation())


def test_recovery_audit_evidence_is_bounded_and_secret_free() -> None:
    evidence = AccountRecoveryAuditEvidence.rejected(
        request=administrative_request(),
        occurred_at=OCCURRED_AT,
        reason="authorization_denied",
    )

    assert {field.name for field in fields(evidence)} == {
        "actor_id",
        "target_actor_id",
        "occurred_at",
        "correlation_id",
        "mode",
        "procedure_identity",
        "reason",
        "outcome",
        "previous_state",
        "resulting_state",
    }
    assert evidence.mode == "administrative"
    assert "secret" not in repr(evidence)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("reason", "secret=value"),
        ("reason", "x" * 65),
        ("procedure_identity", "operator/alice?token=secret"),
        ("procedure_identity", "x" * 65),
    ],
)
def test_recovery_reason_and_procedure_are_bounded_safe_identifiers(
    field_name: str,
    value: str,
) -> None:
    arguments: dict[str, object] = {
        "mode": "emergency",
        "actor_id": None,
        "target_actor_id": UUID(int=10),
        "actor_class": None,
        "target_class": "owner",
        "request_source": "production-console",
        "correlation_id": UUID(int=11),
        "reason": "documented_emergency_recovery",
        "procedure_identity": "owner_recovery_v1",
    }
    arguments[field_name] = value

    with pytest.raises(ValueError, match=r"^invalid account recovery context$"):
        AccountRecoveryRequest(**arguments)  # type: ignore[arg-type]


class ResolvingAccounts:
    def __init__(self, accounts: dict[UUID, RecoveryAccount]) -> None:
        self.accounts = accounts

    def resolve(self, actor_id: UUID) -> RecoveryAccount | None:
        return self.accounts.get(actor_id)


class RecordingPreauthorizationVerifier:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, str, UUID]] = []

    def verify(self, actor_id: UUID, proof_identity: str, correlation_id: UUID) -> bool:
        self.calls.append((actor_id, proof_identity, correlation_id))
        return self.allowed


class RecordingEmergencyProcedureVerifier:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, UUID, UUID]] = []

    def verify(self, procedure_identity: str, target_actor_id: UUID, correlation_id: UUID) -> bool:
        self.calls.append((procedure_identity, target_actor_id, correlation_id))
        return self.allowed


class CollectingAuthorizationAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryAuthorizationAuditEvidence] = []

    def record(self, evidence: RecoveryAuthorizationAuditEvidence) -> None:
        self.evidence.append(evidence)


def trusted_authorizer(
    accounts: dict[UUID, RecoveryAccount],
    *,
    preauthorization: RecordingPreauthorizationVerifier | None = None,
    emergency: RecordingEmergencyProcedureVerifier | None = None,
) -> TrustedAccountRecoveryAuthorizer:
    return TrustedAccountRecoveryAuthorizer(
        account_resolver=ResolvingAccounts(accounts),
        password_preauthorization_verifier=preauthorization or RecordingPreauthorizationVerifier(),
        emergency_procedure_verifier=emergency or RecordingEmergencyProcedureVerifier(),
        administrative_authorization=AdministrativeRecoveryAuthorizationService(
            clock=lambda: OCCURRED_AT,
            audit_sink=CollectingAuthorizationAuditSink(),
        ),
    )


def test_trusted_authorizer_resolves_classes_and_requires_password_preauthorization() -> None:
    request = administrative_request(actor_class="staff", target_class="owner")
    preauthorization = RecordingPreauthorizationVerifier()
    authorizer = trusted_authorizer(
        {
            UUID(int=1): RecoveryAccount(str(UUID(int=1)), "owner"),
            UUID(int=2): RecoveryAccount(str(UUID(int=2)), "manager"),
        },
        preauthorization=preauthorization,
    )

    assert authorizer.authorize(request)
    assert preauthorization.calls == [
        (request.actor_id, request.authorization_proof_identity, request.correlation_id)
    ]
    assert request.request_source == "trusted-admin-source"
    assert request.authorization_proof_identity is not None
    assert request.authorization_proof_identity not in repr(request)


def test_trusted_authorizer_fails_closed_for_unknown_target_or_unverified_proof() -> None:
    request = administrative_request()
    denied_proof = RecordingPreauthorizationVerifier(False)
    accounts = {
        UUID(int=1): RecoveryAccount(str(UUID(int=1)), "owner"),
        UUID(int=2): RecoveryAccount(str(UUID(int=2)), "manager"),
    }

    assert not trusted_authorizer(
        {UUID(int=1): RecoveryAccount(str(UUID(int=1)), "owner")},
    ).authorize(request)
    assert not trusted_authorizer(
        accounts,
        preauthorization=denied_proof,
    ).authorize(request)
    assert not trusted_authorizer(accounts).authorize(
        replace(request, authorization_proof_identity=None)
    )


def test_trusted_authorizer_requires_registered_emergency_procedure_for_resolved_owner() -> None:
    request = AccountRecoveryRequest(
        mode="emergency",
        actor_id=None,
        target_actor_id=UUID(int=10),
        actor_class=None,
        target_class="staff",
        request_source="production-console",
        correlation_id=UUID(int=11),
        reason="documented_emergency_recovery",
        procedure_identity="owner_recovery_v1",
    )
    emergency = RecordingEmergencyProcedureVerifier()

    assert trusted_authorizer(
        {UUID(int=10): RecoveryAccount(str(UUID(int=10)), "owner")},
        emergency=emergency,
    ).authorize(request)
    assert emergency.calls == [("owner_recovery_v1", UUID(int=10), UUID(int=11))]


def test_postgres_administrative_recovery_mutates_revokes_and_audits_in_one_transaction() -> None:
    connection = RecordingConnection()
    repository = PostgresAccountRecoveryRepository(
        connection=connection,
        recovery_code_verifier=StubRecoveryCodeVerifier(),
    )

    result = repository.recover_atomically(
        administrative_request(),
        AccountRecoveryMutation(password_credential=password_mutation().password_credential),
        None,
    )

    statements = [query for query, _ in connection.cursor_instance.executions]
    assert result == AccountRecoveryResult(
        completed=True,
        password_changed=True,
        mfa_disabled=False,
        recovery_code_consumed=False,
        sessions_revoked=2,
    )
    assert any("app.perform_account_recovery" in query for query in statements)
    assert not any("UPDATE app.password_credentials" in query for query in statements)
    assert not any("INSERT INTO app.account_recovery_audit_events" in query for query in statements)
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_postgres_owner_recovery_code_is_consumed_with_revocation_and_audit_atomically() -> None:
    cursor = RecordingCursor()
    cursor.recovery_rows = [(UUID(int=50), "$argon2id$valid", None, None, None)]
    connection = RecordingConnection(cursor)
    repository = PostgresAccountRecoveryRepository(
        connection=connection,
        recovery_code_verifier=StubRecoveryCodeVerifier(),
    )
    request = AccountRecoveryRequest(
        mode="recovery_code",
        actor_id=UUID(int=7),
        target_actor_id=UUID(int=7),
        actor_class="owner",
        target_class="owner",
        request_source="password-verified-preauth",
        correlation_id=UUID(int=8),
        reason="mfa_recovery",
    )

    result = repository.recover_atomically(
        request,
        AccountRecoveryMutation(),
        "valid-code",
    )

    statements = [query for query, _ in cursor.executions]
    assert result.recovery_code_consumed
    assert any("app.perform_account_recovery" in query for query in statements)
    assert not any("UPDATE app.recovery_codes" in query for query in statements)
    assert not any("INSERT INTO app.account_recovery_audit_events" in query for query in statements)
    assert connection.commits == 1


def test_postgres_recovery_rolls_back_every_effect_when_a_required_step_fails() -> None:
    class FailingCursor(RecordingCursor):
        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            super().execute(query, parameters)
            if "app.perform_account_recovery" in query:
                raise RuntimeError("audit insert failed")

    connection = RecordingConnection(FailingCursor())
    repository = PostgresAccountRecoveryRepository(
        connection=connection,
        recovery_code_verifier=StubRecoveryCodeVerifier(),
    )

    with pytest.raises(AccountRecoveryFailed, match=r"^account recovery failed$"):
        repository.recover_atomically(
            administrative_request(),
            password_mutation(),
            None,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_postgres_recovery_rejects_a_requested_bundle_that_mutates_nothing() -> None:
    class NoMutationCursor(RecordingCursor):
        def fetchone(self) -> tuple[object, ...] | None:
            return (False, False, False, 0)

    connection = RecordingConnection(NoMutationCursor())
    repository = PostgresAccountRecoveryRepository(
        connection=connection,
        recovery_code_verifier=StubRecoveryCodeVerifier(),
    )

    with pytest.raises(AccountRecoveryFailed, match=r"^account recovery failed$"):
        repository.recover_atomically(
            administrative_request(),
            AccountRecoveryMutation(reset_mfa=True),
            None,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
