"""Focused tests for the bounded Local Login Security Foundation."""

import pytest

from property_rental.local_authentication import (
    AuthenticationAuditEvidence,
    AuthenticationResult,
    BoundedAuthenticationAttemptLimiter,
    LocalAccountCredential,
    LocalAuthenticationService,
    PostgresLocalAccountRepository,
)
from property_rental.password_security import PasswordHashService, PasswordVerification


class StubCursor:
    def __init__(self, row: tuple[str, str, str, str] | None) -> None:
        self.row = row
        self.query = ""
        self.parameters: tuple[str, ...] = ()

    def __enter__(self) -> "StubCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[str, ...]) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self) -> tuple[str, str, str, str] | None:
        return self.row


class StubConnection:
    def __init__(self, row: tuple[str, str, str, str] | None) -> None:
        self.cursor_instance = StubCursor(row)

    def cursor(self) -> StubCursor:
        return self.cursor_instance


def test_repository_normalizes_username_through_local_account_persistence() -> None:
    connection = StubConnection(
        ("actor-7", "active", "required", "$argon2id$v=19$parameters$salt-hash")
    )
    repository = PostgresLocalAccountRepository(connection)

    account = repository.find_by_username("  Operator  ")

    assert connection.cursor_instance.parameters == ("operator",)
    assert "app.user_accounts" in connection.cursor_instance.query
    assert "app.password_credentials" in connection.cursor_instance.query
    assert account is not None
    assert account.actor_id == "actor-7"
    assert account.lifecycle_state == "active"
    assert account.mfa_policy_class == "required"
    assert account.verifier_encoding == "$argon2id$v=19$parameters$salt-hash"


class StubAccountRepository:
    def __init__(self, account: LocalAccountCredential | None) -> None:
        self.account = account

    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        return self.account


class RecordingAccountRepository(StubAccountRepository):
    def __init__(self, account: LocalAccountCredential | None) -> None:
        super().__init__(account)
        self.usernames: list[str] = []

    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        self.usernames.append(username)
        return super().find_by_username(username)


class StubAttemptLimiter:
    def allow(self, account_key: str, source_key: str) -> bool:
        return True


class CollectingAuditSink:
    def __init__(self) -> None:
        self.evidence: list[AuthenticationAuditEvidence] = []

    def record(self, evidence: AuthenticationAuditEvidence) -> None:
        self.evidence.append(evidence)


def test_authenticates_active_local_account_with_phase_2e_verifier() -> None:
    password_service = PasswordHashService()
    credential = password_service.hash_password("approved password")
    repository = StubAccountRepository(
        LocalAccountCredential(
            actor_id="actor-9",
            lifecycle_state="active",
            mfa_policy_class="optional",
            verifier_encoding=credential.verifier_encoding,
        )
    )
    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=repository,
        password_service=password_service,
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=audit_sink,
    )

    result = service.authenticate(
        username="Operator",
        password="approved password",
        request_source="source-1",
    )

    assert result.is_authenticated is True
    assert result.actor_id == "actor-9"
    assert result.mfa_policy_class == "optional"
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(
            outcome="authenticated",
            reason="credentials_verified",
            actor_id="actor-9",
        )
    ]


class RecordingPasswordService(PasswordHashService):
    def __init__(self) -> None:
        super().__init__()
        self.verification_calls = 0

    def verify_password(self, password: str, verifier_encoding: str) -> PasswordVerification:
        self.verification_calls += 1
        return super().verify_password(password, verifier_encoding)


@pytest.mark.parametrize("account_kind", ["missing", "wrong-password", "disabled"])
def test_rejections_are_generic_and_perform_one_argon2id_verification(account_kind: str) -> None:
    password_service = RecordingPasswordService()
    credential = password_service.hash_password("stored password")
    account = (
        None
        if account_kind == "missing"
        else LocalAccountCredential(
            actor_id="actor-known",
            lifecycle_state="disabled" if account_kind == "disabled" else "active",
            mfa_policy_class="required",
            verifier_encoding=credential.verifier_encoding,
        )
    )
    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=StubAccountRepository(account),
        password_service=password_service,
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=audit_sink,
    )
    password = "stored password" if account_kind == "disabled" else "submitted password"

    result = service.authenticate(
        username="possibly-known",
        password=password,
        request_source="source-2",
    )

    assert result.is_authenticated is False
    assert result.actor_id is None
    assert password_service.verification_calls == 1
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected")
    ]
    assert password not in repr(result)
    assert password not in repr(audit_sink.evidence)


@pytest.mark.parametrize("bounded_scope", ["account", "source"])
def test_attempt_limiter_enforces_account_and_source_bounds(bounded_scope: str) -> None:
    now = [100.0]
    limiter = BoundedAuthenticationAttemptLimiter(
        max_attempts_per_account=2 if bounded_scope == "account" else 10,
        max_attempts_per_source=2 if bounded_scope == "source" else 10,
        window_seconds=60,
        clock=lambda: now[0],
    )

    def keys(attempt: int) -> tuple[str, str]:
        account = "same-account" if bounded_scope == "account" else f"account-{attempt}"
        source = "same-source" if bounded_scope == "source" else f"source-{attempt}"
        return account, source

    assert limiter.allow(*keys(1)) is True
    assert limiter.allow(*keys(2)) is True
    assert limiter.allow(*keys(3)) is False

    now[0] = 160.0
    assert limiter.allow(*keys(4)) is True


@pytest.mark.parametrize(
    ("max_attempts_per_account", "max_attempts_per_source", "window_seconds"),
    [(0, 1, 1), (1, 0, 1), (1, 1, 0), (-1, 1, 1), (1, -1, 1), (1, 1, -1)],
)
def test_attempt_limiter_rejects_nonpositive_security_configuration(
    max_attempts_per_account: int,
    max_attempts_per_source: int,
    window_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        BoundedAuthenticationAttemptLimiter(
            max_attempts_per_account=max_attempts_per_account,
            max_attempts_per_source=max_attempts_per_source,
            window_seconds=window_seconds,
        )


def test_authentication_throttles_normalized_username_variants_before_lookup() -> None:
    password_service = PasswordHashService()
    credential = password_service.hash_password("stored password")
    repository = RecordingAccountRepository(
        LocalAccountCredential(
            actor_id="actor-known",
            lifecycle_state="active",
            mfa_policy_class="required",
            verifier_encoding=credential.verifier_encoding,
        )
    )
    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=repository,
        password_service=password_service,
        attempt_limiter=BoundedAuthenticationAttemptLimiter(
            max_attempts_per_account=2,
            max_attempts_per_source=10,
            window_seconds=60,
        ),
        audit_sink=audit_sink,
    )

    for username in ("Operator", " operator "):
        result = service.authenticate(
            username=username,
            password="wrong password",
            request_source="source-variant",
        )
        assert result == AuthenticationResult(is_authenticated=False)

    limited_result = service.authenticate(
        username="OPERATOR",
        password="wrong password",
        request_source="source-variant",
    )

    assert limited_result == AuthenticationResult(is_authenticated=False)
    assert repository.usernames == ["Operator", " operator "]
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected"),
        AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected"),
        AuthenticationAuditEvidence(outcome="rejected", reason="rate_limited"),
    ]


class DenyingAttemptLimiter:
    def __init__(self) -> None:
        self.keys: tuple[str, str] | None = None

    def allow(self, account_key: str, source_key: str) -> bool:
        self.keys = (account_key, source_key)
        return False


class UnexpectedLookupRepository:
    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        raise AssertionError("rate-limited authentication must not query account state")


def test_rate_limited_authentication_is_generic_and_skips_account_lookup() -> None:
    limiter = DenyingAttemptLimiter()
    audit_sink = CollectingAuditSink()
    secret = "rate-limited-secret"
    service = LocalAuthenticationService(
        repository=UnexpectedLookupRepository(),
        password_service=PasswordHashService(),
        attempt_limiter=limiter,
        audit_sink=audit_sink,
    )

    result = service.authenticate(
        username="  Operator  ",
        password=secret,
        request_source="source-limited",
    )

    assert result.is_authenticated is False
    assert result.actor_id is None
    assert limiter.keys == ("operator", "source-limited")
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="rate_limited")
    ]
    assert secret not in repr(result)
    assert secret not in repr(audit_sink.evidence)
