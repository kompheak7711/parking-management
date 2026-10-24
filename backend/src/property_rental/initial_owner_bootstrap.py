"""Protected, transactional initial Owner bootstrap boundaries."""

import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from property_rental.password_security import blocked_passwords as shared_blocked_passwords
from property_rental.password_security import validate_new_password
from property_rental.visible_text import tidy_spaces

RECOVERY_CODE_COUNT: Final = 10
BOOTSTRAP_ACKNOWLEDGEMENT: Final = "I HAVE STORED THE RECOVERY CODES"


@dataclass(frozen=True, slots=True)
class InitialOwnerBootstrapClosureRequest:
    """Bounded non-secret context for one protected closure attempt."""

    target_actor_id: UUID
    correlation_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.target_actor_id, UUID) or not isinstance(self.correlation_id, UUID):
            raise ValueError("invalid initial Owner bootstrap closure context")


@dataclass(frozen=True, slots=True)
class InitialOwnerBootstrapClosureResult:
    """Generic durable outcome without account or credential detail."""

    established: bool


class InitialOwnerBootstrapClosureFailed(RuntimeError):
    """Generic fail-closed persistence failure without database detail."""


class InitialOwnerBootstrapClosureRepository(Protocol):
    """Atomic one-time closure and immutable audit persistence boundary."""

    def establish_atomically(
        self,
        request: InitialOwnerBootstrapClosureRequest,
    ) -> InitialOwnerBootstrapClosureResult: ...


class InitialOwnerBootstrapClosureCursor(Protocol):
    """Bounded cursor operations required by the PostgreSQL adapter."""

    def __enter__(self) -> "InitialOwnerBootstrapClosureCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class InitialOwnerBootstrapClosureConnection(Protocol):
    """Caller-owned transaction used by the PostgreSQL adapter."""

    def cursor(self) -> InitialOwnerBootstrapClosureCursor: ...


class PostgresInitialOwnerBootstrapClosureRepository:
    """Invoke the closure inside the caller's Owner-bootstrap transaction."""

    def __init__(self, connection: InitialOwnerBootstrapClosureConnection) -> None:
        self._connection = connection

    def establish_atomically(
        self,
        request: InitialOwnerBootstrapClosureRequest,
    ) -> InitialOwnerBootstrapClosureResult:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT established
                    FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)
                    """,
                    (request.target_actor_id, request.correlation_id),
                )
                row = cursor.fetchone()
                if row is None or len(row) != 1 or not isinstance(row[0], bool):
                    raise RuntimeError("invalid bootstrap closure result")
                return InitialOwnerBootstrapClosureResult(established=row[0])
        except Exception:
            raise InitialOwnerBootstrapClosureFailed(
                "initial Owner bootstrap closure failed"
            ) from None


class InitialOwnerBootstrapClosureGuard:
    """Future protected bootstrap composition seam over the durable guard."""

    def __init__(self, repository: InitialOwnerBootstrapClosureRepository) -> None:
        self._repository = repository

    def establish(
        self,
        request: InitialOwnerBootstrapClosureRequest,
    ) -> InitialOwnerBootstrapClosureResult:
        return self._repository.establish_atomically(request)


@dataclass(frozen=True, slots=True)
class BootstrapRequest:
    """Non-secret identity and correlation values for one protected attempt."""

    actor_id: UUID
    correlation_id: UUID
    enrollment_id: UUID
    recovery_set_id: UUID
    recovery_code_ids: tuple[UUID, ...]
    username: str
    display_name: str
    audit_name: str

    def __post_init__(self) -> None:
        identifiers = (
            self.actor_id,
            self.correlation_id,
            self.enrollment_id,
            self.recovery_set_id,
            *self.recovery_code_ids,
        )
        if (
            len(self.recovery_code_ids) != RECOVERY_CODE_COUNT
            or len(set(self.recovery_code_ids)) != RECOVERY_CODE_COUNT
            or not all(isinstance(identifier, UUID) for identifier in identifiers)
        ):
            raise ValueError(
                "initial Owner bootstrap requires exactly 10 distinct code identifiers"
            )
        if any(
            not value or value != value.strip() or not value.isprintable()
            for value in (self.username, self.display_name, self.audit_name)
        ):
            raise ValueError("invalid initial Owner bootstrap identity")
        # Login sub-slice L2d review round 1 (security): sign-in tidies the typed username
        # (Q-2026-10-22-170 (a)), so a username that tidying would change, such as one with two
        # spaces in a row, is refused until L7 makes the bootstrap store the sign-in form.
        if tidy_spaces(self.username) != self.username:
            raise ValueError("invalid initial Owner bootstrap identity")


@dataclass(frozen=True, slots=True)
class BootstrapSecretBundle:
    """Ephemeral secret and protected material with a fully redacted representation."""

    password_verifier: str = field(repr=False)
    password_algorithm: str
    password_work_factors: Mapping[str, int]
    totp_plaintext: str = field(repr=False)
    totp_ciphertext: bytes = field(repr=False)
    totp_nonce: bytes
    totp_key_identifier: str
    recovery_plaintexts: tuple[str, ...] = field(repr=False)
    recovery_verifiers: tuple[str, ...] = field(repr=False)
    recovery_algorithm: str
    recovery_work_factors: Mapping[str, int]

    def __post_init__(self) -> None:
        if (
            len(self.recovery_plaintexts) != RECOVERY_CODE_COUNT
            or len(self.recovery_verifiers) != RECOVERY_CODE_COUNT
            or len(set(self.recovery_plaintexts)) != RECOVERY_CODE_COUNT
        ):
            raise ValueError("initial Owner bootstrap requires exactly 10 recovery codes")


class BootstrapPasswordPolicy:
    """Apply the Owner-approved local password acceptance policy (the shared new-password rule
    of `password_security`, login sub-slice L4; unchanged for the bootstrap)."""

    def __init__(self, *, blocked_passwords: set[str]) -> None:
        self._blocked = shared_blocked_passwords(blocked_passwords)

    def accept(self, password: str, *, context: tuple[str, ...]) -> str:
        """Return NFC material only when the entire password is acceptable."""
        try:
            return validate_new_password(password, blocked=self._blocked, context=context)
        except ValueError:
            raise ValueError("bootstrap password rejected") from None


class BootstrapRepository(Protocol):
    """Caller-owned atomic PostgreSQL transaction boundary."""

    def begin_attempt(self, request: BootstrapRequest) -> bool: ...

    def establish(
        self,
        request: BootstrapRequest,
        bundle: BootstrapSecretBundle,
        *,
        timeout_milliseconds: int,
    ) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class BootstrapTerminal(Protocol):
    """Controlling-TTY-only secret input and one-time presentation boundary."""

    def read_password(self) -> str: ...

    def present_totp_and_read_code(self, secret: str, *, deadline: float) -> str: ...

    def present_recovery_codes(self, codes: tuple[str, ...], *, deadline: float) -> None: ...

    def read_acknowledgement(self, *, deadline: float) -> str: ...


class BootstrapMaterialFactory(Protocol):
    """Generate and protect all credential material before atomic persistence."""

    def create(
        self, *, request: BootstrapRequest, normalized_password: str
    ) -> BootstrapSecretBundle: ...

    def verify_totp(self, bundle: BootstrapSecretBundle, candidate: str) -> bool: ...


class BootstrapFailed(RuntimeError):
    """Generic fail-closed result that carries no secret or persistence detail."""


class InitialOwnerBootstrapService:
    """Coordinate protected input, atomic persistence, presentation, acknowledgement, and commit."""

    def __init__(
        self,
        *,
        repository: BootstrapRepository,
        terminal: BootstrapTerminal,
        password_policy: BootstrapPasswordPolicy,
        material_factory: BootstrapMaterialFactory,
        ceremony_timeout_seconds: int,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ceremony_timeout_seconds <= 0:
            raise ValueError("bootstrap ceremony timeout must be positive")
        self._repository = repository
        self._terminal = terminal
        self._password_policy = password_policy
        self._material_factory = material_factory
        self._timeout = ceremony_timeout_seconds
        self._monotonic_clock = monotonic_clock

    def _remaining_milliseconds(self, deadline: float) -> int:
        remaining = deadline - self._monotonic_clock()
        if remaining <= 0:
            raise TimeoutError("bootstrap ceremony deadline expired")
        return max(1, math.ceil(remaining * 1000))

    def _require_before_deadline(self, deadline: float) -> None:
        self._remaining_milliseconds(deadline)

    def run(self, request: BootstrapRequest) -> None:
        """Complete one bootstrap or roll back every durable effect."""
        try:
            if not self._repository.begin_attempt(request):
                self._repository.commit()
                raise BootstrapFailed("initial Owner bootstrap failed")
            password = self._terminal.read_password()
            normalized_password = self._password_policy.accept(
                password,
                context=(request.username, request.display_name, request.audit_name),
            )
            bundle = self._material_factory.create(
                request=request,
                normalized_password=normalized_password,
            )
            deadline = self._monotonic_clock() + self._timeout
            totp_candidate = self._terminal.present_totp_and_read_code(
                bundle.totp_plaintext,
                deadline=deadline,
            )
            self._require_before_deadline(deadline)
            if not self._material_factory.verify_totp(bundle, totp_candidate):
                raise RuntimeError("TOTP enrollment confirmation failed")
            if not self._repository.establish(
                request,
                bundle,
                timeout_milliseconds=self._remaining_milliseconds(deadline),
            ):
                raise RuntimeError("bootstrap establishment rejected")
            self._require_before_deadline(deadline)
            self._terminal.present_recovery_codes(bundle.recovery_plaintexts, deadline=deadline)
            self._require_before_deadline(deadline)
            acknowledgement = self._terminal.read_acknowledgement(deadline=deadline)
            if acknowledgement != BOOTSTRAP_ACKNOWLEDGEMENT:
                raise RuntimeError("bootstrap acknowledgement failed")
            self._require_before_deadline(deadline)
            self._repository.commit()
        except BootstrapFailed:
            raise
        except Exception:
            self._repository.rollback()
            raise BootstrapFailed("initial Owner bootstrap failed") from None


class PostgresInitialOwnerBootstrapRepository:
    """Use only the migration-published bootstrap functions in one caller-owned transaction."""

    def __init__(self, connection: InitialOwnerBootstrapClosureConnection) -> None:
        self._connection = connection

    def begin_attempt(self, request: BootstrapRequest) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT app.begin_initial_owner_bootstrap_attempt(%s, %s)",
                (request.actor_id, request.correlation_id),
            )
            row = cursor.fetchone()
        if row is None or len(row) != 1 or not isinstance(row[0], bool):
            raise RuntimeError("invalid bootstrap preflight result")
        return row[0]

    def establish(
        self,
        request: BootstrapRequest,
        bundle: BootstrapSecretBundle,
        *,
        timeout_milliseconds: int,
    ) -> bool:
        if timeout_milliseconds <= 0:
            raise RuntimeError("bootstrap statement timeout expired")
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                (f"{timeout_milliseconds}ms",),
            )
            cursor.execute(
                """
                SELECT app.establish_initial_owner_bootstrap(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s, %s::uuid[], %s::text[], %s, %s::jsonb
                )
                """,
                (
                    request.actor_id,
                    request.correlation_id,
                    request.enrollment_id,
                    request.recovery_set_id,
                    request.username.casefold(),
                    request.display_name,
                    request.audit_name,
                    bundle.password_verifier,
                    bundle.password_algorithm,
                    json.dumps(dict(bundle.password_work_factors), sort_keys=True),
                    bundle.totp_ciphertext,
                    bundle.totp_nonce,
                    bundle.totp_key_identifier,
                    list(request.recovery_code_ids),
                    list(bundle.recovery_verifiers),
                    bundle.recovery_algorithm,
                    json.dumps(dict(bundle.recovery_work_factors), sort_keys=True),
                ),
            )
            row = cursor.fetchone()
        if row is None or len(row) != 1 or not isinstance(row[0], bool):
            raise RuntimeError("invalid bootstrap establishment result")
        return row[0]

    def commit(self) -> None:
        commit = getattr(self._connection, "commit", None)
        if commit is None:
            raise RuntimeError("bootstrap connection cannot commit")
        commit()

    def rollback(self) -> None:
        rollback = getattr(self._connection, "rollback", None)
        if rollback is None:
            raise RuntimeError("bootstrap connection cannot roll back")
        rollback()
