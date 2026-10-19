"""Hand-built reversals in tests after V1-056 sub-slice 10h-1 (BR-SETTLE-013).

Since migration 20270108_165 an allocation or Customer Credit application that a closed Final
Settlement relied on is reversed only through a correction of that Settlement confirmed in the
same transaction (owner answers 3 and 4 to Q-2026-10-06-36); the one-call reversal and every other
writer is refused (P5S01). Owner answer (a) to Q-2026-10-19-142: committed tests that used such a
reversal only to reach the state they check keep their scenario with a hand-built set-up, which
first asserts the 10h-1 refusal.

- ``reverse_allocation_by_hand`` asserts that the one-call allocation reversal is refused and
  writes nothing, then runs the same database function as the database owner with only the 10h-1
  allocation trigger disabled, inside that one transaction.
- ``relied_on_triggers_disabled`` disables the two 10h-1 triggers inside the caller's owner
  transaction and enables them again before it ends.
- ``relied_on_refusal`` runs one action in a savepoint and returns its refusal.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from property_rental.payment_allocation import AllocationConflictError, ReverseAllocationCommand
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations

CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
ALLOCATION_TRIGGER = (
    "app.payment_allocation_reversals",
    "a0_payment_allocation_reversals_relied_on",
)
CREDIT_TRIGGER = (
    "app.customer_credit_application_reversals",
    "a1_customer_credit_application_reversals_relied_on",
)


@contextmanager
def relied_on_triggers_disabled(
    connection: psycopg.Connection[Any],
    triggers: tuple[tuple[str, str], ...] = (ALLOCATION_TRIGGER, CREDIT_TRIGGER),
) -> Iterator[None]:
    """Inside the caller's owner transaction only: the named 10h-1 triggers are disabled, and
    enabled again before the transaction ends (a failed transaction rolls the change back). An
    autocommit connection would commit the disable at once, so it is refused (review round 2,
    security note 2). A body that ends the transaction would commit the disable too: the triggers
    are then enabled again and committed before the misuse is reported (review round 3 notes)."""
    assert not connection.autocommit
    transaction = "SELECT pg_current_xact_id()::text"
    for table, trigger in triggers:
        connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
    started = connection.execute(transaction).fetchone()
    try:
        yield
    finally:
        if connection.info.transaction_status != TransactionStatus.INERROR:
            for table, trigger in triggers:
                connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
            if connection.execute(transaction).fetchone() != started:
                connection.commit()
                raise AssertionError("the body ended the transaction that disabled the triggers")


def relied_on_refusal(
    connection: psycopg.Connection[Any], action: Callable[[], object]
) -> tuple[str | None, str | None]:
    """The SQLSTATE and message of an action on the connection that must be refused, in a
    savepoint that is then rolled back, so the caller's transaction goes on."""
    connection.execute("SAVEPOINT relied_on_refusal")
    try:
        action()
    except psycopg.Error as refused:
        connection.execute("ROLLBACK TO SAVEPOINT relied_on_refusal")
        return refused.sqlstate, refused.diag.message_primary
    connection.execute("ROLLBACK TO SAVEPOINT relied_on_refusal")
    raise AssertionError("the statement was not refused")


def reverse_allocation_by_hand(
    url: str, prop: UUID, human: UUID, allocation: UUID, reason: str
) -> None:
    """Since sub-slice 10h-1 the one-call reversal of an allocation a closed Final Settlement
    relied on is refused, so this state can no longer be reached by it: the refusal is asserted
    first (a conflict, P5S01, nothing written), then the same one-call database function runs as
    the database owner with only the 10h-1 allocation trigger disabled in that transaction."""
    with pytest.raises(AllocationConflictError) as refused:
        allocations().reverse_allocation(
            prop,
            allocation,
            ReverseAllocationCommand(uuid4(), reason),
            actor=allocation_actor(human, prop),
        )
    error = refused.value.__cause__
    assert isinstance(error, psycopg.Error)
    assert (error.sqlstate, error.diag.message_primary) == ("P5S01", CLOSED)
    reversals = (
        "SELECT count(*) FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s"
    )
    digest = hashlib.sha256(f"REVERSE_ALLOCATION:{prop}:{allocation}:{reason}".encode()).hexdigest()
    with psycopg.connect(url) as connection:
        assert connection.execute(reversals, (allocation,)).fetchone() == (0,)
        with relied_on_triggers_disabled(connection, (ALLOCATION_TRIGGER,)):
            connection.execute(
                "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
                (prop, allocation, human, uuid4(), digest, reason),
            )
        assert connection.execute(reversals, (allocation,)).fetchone() == (1,)
