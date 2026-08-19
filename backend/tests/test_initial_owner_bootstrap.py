"""Focused tests for the initial Owner bootstrap closure guard."""

from uuid import UUID

import pytest

from property_rental.initial_owner_bootstrap import (
    InitialOwnerBootstrapClosureFailed,
    InitialOwnerBootstrapClosureGuard,
    InitialOwnerBootstrapClosureRequest,
    InitialOwnerBootstrapClosureResult,
    PostgresInitialOwnerBootstrapClosureRepository,
)


class RecordingCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class FailingCursor(RecordingCursor):
    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        del query, parameters
        raise RuntimeError("database detail must not escape")


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.cursor_instance = cursor

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance


REQUEST = InitialOwnerBootstrapClosureRequest(
    target_actor_id=UUID(int=1),
    correlation_id=UUID(int=2),
)


def test_guard_returns_established_result_from_transactional_repository() -> None:
    repository = PostgresInitialOwnerBootstrapClosureRepository(
        RecordingConnection(RecordingCursor((True,)))
    )

    result = InitialOwnerBootstrapClosureGuard(repository=repository).establish(REQUEST)

    assert result == InitialOwnerBootstrapClosureResult(established=True)


def test_postgres_repository_uses_only_the_guard_in_the_caller_transaction() -> None:
    cursor = RecordingCursor((False,))
    connection = RecordingConnection(cursor)
    repository = PostgresInitialOwnerBootstrapClosureRepository(connection)

    result = repository.establish_atomically(REQUEST)

    assert result == InitialOwnerBootstrapClosureResult(established=False)
    assert len(cursor.executions) == 1
    query, parameters = cursor.executions[0]
    assert "app.attempt_initial_owner_bootstrap_closure" in query
    assert "user_accounts" not in query
    assert "bootstrap" not in repr(parameters).lower()
    assert parameters == (REQUEST.target_actor_id, REQUEST.correlation_id)


def test_postgres_repository_returns_generic_failure_to_transaction_owner() -> None:
    connection = RecordingConnection(FailingCursor(None))
    repository = PostgresInitialOwnerBootstrapClosureRepository(connection)

    with pytest.raises(
        InitialOwnerBootstrapClosureFailed,
        match=r"^initial Owner bootstrap closure failed$",
    ) as failure:
        repository.establish_atomically(REQUEST)

    assert failure.value.__cause__ is None


def test_postgres_repository_rejects_missing_or_malformed_database_result() -> None:
    for row in (None, (), ("established",), (True, UUID(int=1))):
        connection = RecordingConnection(RecordingCursor(row))
        repository = PostgresInitialOwnerBootstrapClosureRepository(connection)

        with pytest.raises(InitialOwnerBootstrapClosureFailed):
            repository.establish_atomically(REQUEST)


def test_request_requires_uuid_target_and_correlation_identifiers() -> None:
    with pytest.raises(ValueError, match=r"^invalid initial Owner bootstrap closure context$"):
        InitialOwnerBootstrapClosureRequest(
            target_actor_id="owner",  # type: ignore[arg-type]
            correlation_id=UUID(int=2),
        )
    with pytest.raises(ValueError, match=r"^invalid initial Owner bootstrap closure context$"):
        InitialOwnerBootstrapClosureRequest(
            target_actor_id=UUID(int=1),
            correlation_id="correlation",  # type: ignore[arg-type]
        )
