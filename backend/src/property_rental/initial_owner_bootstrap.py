"""Transactional initial Owner bootstrap closure guard boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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
