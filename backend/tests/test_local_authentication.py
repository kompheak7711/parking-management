"""Focused tests for the bounded Local Login Security Foundation."""

import hashlib

import pytest

from property_rental.local_authentication import (
    AuthenticationAuditEvidence,
    AuthenticationResult,
    BoundedAuthenticationAttemptLimiter,
    LocalAccountCredential,
    LocalAuthenticationService,
    PostgresLocalAccountRepository,
    verifier_digest,
)
from property_rental.password_security import PasswordHashService, PasswordVerification


class StubCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
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

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class StubConnection:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.cursor_instance = StubCursor(row)

    def cursor(self) -> StubCursor:
        return self.cursor_instance


def test_repository_normalizes_username_through_local_account_persistence() -> None:
    connection = StubConnection(
        ("actor-7", "active", "required", "$argon2id$v=19$parameters$salt-hash", None, False)
    )
    repository = PostgresLocalAccountRepository(connection)

    account = repository.find_by_username("  Operator  ")

    assert connection.cursor_instance.parameters == ("operator",)
    assert "app.user_accounts" in connection.cursor_instance.query
    assert "app.password_credentials" in connection.cursor_instance.query
    # Login slice L1a: only an account with a class can be found (fail closed).
    assert "JOIN app.user_account_classes" in connection.cursor_instance.query
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


def test_sign_in_lookup_and_limiter_use_the_creation_rule_for_the_username() -> None:
    """DL-081, Q-2026-10-22-169 (a) gap 3 (login sub-slice L2c, review round 1): the sign-in
    lookup and the attempt limiter key remove U+200B and make the username NFC, as account
    creation does, so every spelling of one username is looked up and counted as one."""
    for typed, expected in (
        (" Dara\u200b.Sok ", "dara.sok"),
        ("dara.sok", "dara.sok"),
        ("Dara.Sok", "dara.sok"),
        ("Cafe\u0301.Desk", "caf\u00e9.desk"),
    ):
        connection = StubConnection(None)
        assert PostgresLocalAccountRepository(connection).find_by_username(typed) is None
        assert connection.cursor_instance.parameters == (expected,)

    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=StubAccountRepository(None),
        password_service=PasswordHashService(),
        attempt_limiter=BoundedAuthenticationAttemptLimiter(
            max_attempts_per_account=1,
            max_attempts_per_source=10,
            window_seconds=60,
        ),
        audit_sink=audit_sink,
    )
    for username in ("dara.sok", "Dara\u200b.Sok"):
        result = service.authenticate(
            username=username,
            password="wrong password",
            request_source="source-l2c",
        )
        assert result == AuthenticationResult(is_authenticated=False)
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected"),
        AuthenticationAuditEvidence(outcome="rejected", reason="rate_limited"),
    ]


def test_sign_in_lookup_and_limiter_tidy_spaces_in_the_typed_username() -> None:
    """DL-081, Q-2026-10-22-170 (a) (login sub-slice L2d): the sign-in lookup and the attempt
    limiter key tidy the typed username as account creation does (every space separator becomes
    U+0020, a run of them one, none at either end), so "Sokha  Chan" typed with two spaces on an
    iPad finds and counts the account saved as "sokha chan"."""
    for typed in ("Sokha  Chan", " Sokha\u00a0Chan ", "sokha\u3000\u2009chan", "sokha chan"):
        connection = StubConnection(None)
        assert PostgresLocalAccountRepository(connection).find_by_username(typed) is None
        assert connection.cursor_instance.parameters == ("sokha chan",)

    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=StubAccountRepository(None),
        password_service=PasswordHashService(),
        attempt_limiter=BoundedAuthenticationAttemptLimiter(
            max_attempts_per_account=1,
            max_attempts_per_source=10,
            window_seconds=60,
        ),
        audit_sink=audit_sink,
    )
    for username in ("sokha chan", "Sokha  Chan"):
        result = service.authenticate(
            username=username,
            password="wrong password",
            request_source="source-l2d",
        )
        assert result == AuthenticationResult(is_authenticated=False)
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected"),
        AuthenticationAuditEvidence(outcome="rejected", reason="rate_limited"),
    ]


class RecordingSignInWaits:
    """A stand-in for the database count of wrong tries (login sub-slice L3b)."""

    def __init__(self, waiting: int | None = None, started: int | None = None) -> None:
        self.waiting = waiting
        self.started = started
        self.asked: list[tuple[str, str]] = []
        self.recorded: list[tuple[str, str]] = []

    def wait_seconds(self, account_key: str, source_key: str) -> int | None:
        self.asked.append((account_key, source_key))
        return self.waiting

    def record_wrong_try(self, account_key: str, source_key: str) -> int | None:
        self.recorded.append((account_key, source_key))
        return self.started


def test_a_try_during_a_sign_in_wait_is_refused_before_the_lookup_and_the_password_check() -> None:
    """DL-081 (the owner's wait rule): a try during a wait is refused without looking the
    account up or checking the password, adds no wrong try and carries the seconds left."""
    waits = RecordingSignInWaits(waiting=120)
    audit_sink = CollectingAuditSink()
    secret = "waiting-secret"
    service = LocalAuthenticationService(
        repository=UnexpectedLookupRepository(),
        password_service=PasswordHashService(),
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=audit_sink,
        sign_in_waits=waits,
    )

    result = service.authenticate(username=" Sokha ", password=secret, request_source="desk")

    assert result == AuthenticationResult(is_authenticated=False, wait_seconds=120)
    assert waits.asked == [("sokha", "desk")] and waits.recorded == []
    assert audit_sink.evidence == [
        AuthenticationAuditEvidence(outcome="rejected", reason="sign_in_wait")
    ]
    assert secret not in repr(audit_sink.evidence)


@pytest.mark.parametrize("account_kind", ["unknown", "disabled", "wrong_password"])
def test_every_refused_password_check_records_one_wrong_try(account_kind: str) -> None:
    """DL-081: an unknown username, a disabled account and a wrong password each record one
    wrong try under the normalized username and the source, and carry the wait it started."""
    password_service = PasswordHashService()
    credential = password_service.hash_password("approved password")
    account = (
        None
        if account_kind == "unknown"
        else LocalAccountCredential(
            actor_id="actor-3",
            lifecycle_state="disabled" if account_kind == "disabled" else "active",
            mfa_policy_class="optional",
            verifier_encoding=credential.verifier_encoding,
        )
    )
    waits = RecordingSignInWaits(started=300)
    service = LocalAuthenticationService(
        repository=StubAccountRepository(account),
        password_service=password_service,
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=CollectingAuditSink(),
        sign_in_waits=waits,
    )
    password = "wrong password" if account_kind == "wrong_password" else "approved password"

    result = service.authenticate(username="Sokha", password=password, request_source="desk")

    assert result == AuthenticationResult(is_authenticated=False, wait_seconds=300)
    assert waits.recorded == [("sokha", "desk")]


def test_a_correct_password_records_no_wrong_try() -> None:
    """DL-081: a correct password neither records a wrong try nor carries a wait; the count is
    cleared where the session is written."""
    password_service = PasswordHashService()
    credential = password_service.hash_password("approved password")
    waits = RecordingSignInWaits()
    service = LocalAuthenticationService(
        repository=StubAccountRepository(
            LocalAccountCredential(
                actor_id="actor-4",
                lifecycle_state="active",
                mfa_policy_class="optional",
                verifier_encoding=credential.verifier_encoding,
            )
        ),
        password_service=password_service,
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=CollectingAuditSink(),
        sign_in_waits=waits,
    )

    result = service.authenticate(
        username="Sokha", password="approved password", request_source="desk"
    )

    assert result.is_authenticated is True and result.wait_seconds is None
    assert waits.asked == [("sokha", "desk")] and waits.recorded == []
    # Q-2026-10-23-177 (a): the digest of the verifier checked, for the session transaction.
    assert result.verifier_digest == verifier_digest(credential.verifier_encoding)
    assert result.verifier_digest == hashlib.sha256(credential.verifier_encoding.encode()).digest()
    # Review round 4: verifier material is never represented.
    assert result.verifier_digest.hex() not in repr(result)


@pytest.mark.parametrize("expired", [False, True])
def test_a_one_time_password_signs_in_until_it_expires_and_then_counts_as_a_wrong_try(
    expired: bool,
) -> None:
    """Login sub-slice L4 (Q-2026-10-24-185): the right one-time password is checked like any
    password and the result names it, so the flow asks for the new password; after its 24 hours
    (read on the database clock) the same password gets the generic refusal and one wrong try,
    after the one Argon2id check."""
    password_service = RecordingPasswordService()
    credential = password_service.hash_password("k7m2-x9qp-4hrt-w3nd")
    waits = RecordingSignInWaits(started=0)
    audit_sink = CollectingAuditSink()
    service = LocalAuthenticationService(
        repository=StubAccountRepository(
            LocalAccountCredential(
                actor_id="actor-5",
                lifecycle_state="active",
                mfa_policy_class="optional",
                verifier_encoding=credential.verifier_encoding,
                one_time_password_id="otp-1",
                one_time_password_expired=expired,
            )
        ),
        password_service=password_service,
        attempt_limiter=StubAttemptLimiter(),
        audit_sink=audit_sink,
        sign_in_waits=waits,
    )

    result = service.authenticate(
        username="Sokha", password="k7m2-x9qp-4hrt-w3nd", request_source="desk"
    )

    assert password_service.verification_calls == 1
    if expired:
        assert result.is_authenticated is False and result.one_time_password_id is None
        assert waits.recorded == [("sokha", "desk")]
        assert audit_sink.evidence == [
            AuthenticationAuditEvidence(outcome="rejected", reason="credentials_rejected")
        ]
    else:
        assert result.is_authenticated is True
        assert result.one_time_password_id == "otp-1"
        assert waits.recorded == []
    assert "k7m2-x9qp-4hrt-w3nd" not in repr(result)


def test_the_account_query_reads_the_one_time_password_on_the_database_clock() -> None:
    """Login sub-slice L4: the lookup joins the credential's one-time password and compares its
    end with the database's clock, never the app's."""
    connection = StubConnection(
        ("actor-6", "active", "optional", "$argon2id$v=19$stub", "otp-2", False)
    )
    account = PostgresLocalAccountRepository(connection).find_by_username("Sokha")

    assert account is not None
    assert account.one_time_password_id == "otp-2"
    assert account.one_time_password_expired is False
    query = connection.cursor_instance.query
    assert "app.one_time_passwords" in query
    assert "issued.expires_at <= statement_timestamp()" in query
