"""Real PostgreSQL coverage of adding and turning off Refund methods with Settings access (V1-056
slice 11h; owner answer of 2026-10-25; BR-REFUND-014).

Only the Owner and people ticked for Settings access add a Refund method or turn one off or on
again; at least one Refund method always stays on; each real change is audited.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.refund import (
    AddRefundMethodCommand,
    RefundAuthorizationError,
    RefundConflictError,
    RefundNotFoundError,
)
from test_credit_migration import actor, source
from test_invoice_migration import runtime_database_url
from test_refund_draft_migration import service
from test_reservation_migration import migrated_database_url  # noqa: F401

ADD = "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)"
TURN = "SELECT app.set_refund_method_active(%s,%s,%s,%s,%s)"


def audits(url: str, method: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT action,authorization_reference,previous_state->>'active',"
            "resulting_state->>'active' FROM app.audit_events "
            "WHERE entity_type='refund_method' AND entity_id=%s ORDER BY occurred_at,id",
            (method,),
        ).fetchall()


def code() -> str:
    return f"WING_{uuid4().hex[:8].upper()}"


@pytest.fixture
def others_back_on(migrated_database_url: str) -> Iterator[list[UUID]]:  # noqa: F811
    """The methods turned off by a test are turned on again after it (the list is shared)."""
    turned: list[UUID] = []
    yield turned
    human, prop, _, _ = source(migrated_database_url)
    with psycopg.connect(runtime_database_url()) as connection:
        for method in turned:
            connection.execute(TURN, (prop, human, method, True, "settings.manage"))


def test_settings_access_adds_a_refund_method_that_starts_on_and_is_audited(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _ = source(migrated_database_url)
    settings = actor(human, prop, "settings.manage")
    method, wing = uuid4(), code()
    added = service().add_refund_method(
        prop, AddRefundMethodCommand(method, wing, "Wing money transfer"), actor=settings
    )
    assert (added["id"], added["code"], added["active"], added["seeded"]) == (
        str(method),
        wing,
        True,
        False,
    )
    # A repeat of the same request answers the same method and writes nothing more.
    assert (
        service().add_refund_method(
            prop, AddRefundMethodCommand(method, wing, "Wing money transfer"), actor=settings
        )
        == added
    )
    assert audits(migrated_database_url, method) == [
        ("refund_method.added", "settings.manage", None, "true")
    ]
    listed = cast(list[dict[str, Any]], service().refund_methods(prop, actor=settings)["items"])
    assert added in listed

    with pytest.raises(RefundConflictError) as used:
        service().add_refund_method(
            prop, AddRefundMethodCommand(uuid4(), wing, "Another name"), actor=settings
        )
    assert isinstance(used.value.__cause__, psycopg.Error)
    assert used.value.__cause__.diag.message_primary == "Refund Method code is already used"
    with pytest.raises(RefundConflictError) as reused:
        service().add_refund_method(
            prop, AddRefundMethodCommand(method, code(), "Wing money transfer"), actor=settings
        )
    assert isinstance(reused.value.__cause__, psycopg.Error)
    assert reused.value.__cause__.diag.message_primary == "Refund Method identity was reused"
    for capability in ("property.manage", "refunds.create", "financial.approve"):
        with pytest.raises(RefundAuthorizationError):
            service().add_refund_method(
                prop,
                AddRefundMethodCommand(uuid4(), code(), "Not allowed"),
                actor=actor(human, prop, capability),
            )
    with psycopg.connect(runtime_database_url()) as connection:
        for reference in ("property.manage", "refunds.create", None):
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(ADD, (prop, human, uuid4(), code(), "Not allowed", reference))
            assert refused.value.sqlstate == "42501"
            connection.rollback()
        for bad in (("wing", "Wing"), (code(), " Wing"), (code(), ""), (code(), "x" * 121)):
            with pytest.raises(psycopg.Error) as invalid:
                connection.execute(ADD, (prop, human, uuid4(), *bad, "settings.manage"))
            assert invalid.value.sqlstate == "22023"
            connection.rollback()
        for empty in (None, UUID(int=0)):
            with pytest.raises(psycopg.Error) as invalid:
                connection.execute(ADD, (prop, human, empty, code(), "Wing", "settings.manage"))
            assert invalid.value.sqlstate == "22023"
            connection.rollback()


def test_a_method_is_turned_off_and_on_again_with_each_change_audited(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _ = source(migrated_database_url)
    settings = actor(human, prop, "settings.manage")
    method = uuid4()
    service().add_refund_method(
        prop, AddRefundMethodCommand(method, code(), "Wing money transfer"), actor=settings
    )
    off = service().set_refund_method_on(prop, method, False, actor=settings)
    assert off["active"] is False
    # Turning off what is off changes nothing and writes no audit event.
    assert service().set_refund_method_on(prop, method, False, actor=settings) == off
    on = service().set_refund_method_on(prop, method, True, actor=settings)
    assert on["active"] is True
    assert audits(migrated_database_url, method) == [
        ("refund_method.added", "settings.manage", None, "true"),
        ("refund_method.turned_off", "settings.manage", "true", "false"),
        ("refund_method.turned_on", "settings.manage", "false", "true"),
    ]
    with pytest.raises(RefundAuthorizationError):
        service().set_refund_method_on(
            prop, method, False, actor=actor(human, prop, "property.manage")
        )
    with pytest.raises(RefundNotFoundError):
        service().set_refund_method_on(prop, uuid4(), False, actor=settings)
    with psycopg.connect(runtime_database_url()) as connection:
        for reference in ("property.manage", None):
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(TURN, (prop, human, method, False, reference))
            assert refused.value.sqlstate == "42501"
            connection.rollback()
        for bad in ((None, False), (method, None)):
            with pytest.raises(psycopg.Error) as invalid:
                connection.execute(TURN, (prop, human, *bad, "settings.manage"))
            assert invalid.value.sqlstate == "22023"
            connection.rollback()


def test_the_last_method_that_is_on_stays_on(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _ = source(migrated_database_url)
    with psycopg.connect(runtime_database_url()) as connection:
        on = [
            UUID(str(row[0]))
            for row in connection.execute(
                "SELECT (item->>'id') FROM jsonb_array_elements("
                "app.list_refund_methods(%s,%s)->'items') item WHERE (item->>'active')::boolean",
                (prop, human),
            ).fetchall()
        ]
        assert len(on) >= 2
        # One transaction, rolled back: the shared list is not changed for other tests.
        for method in on[1:]:
            connection.execute(TURN, (prop, human, method, False, "settings.manage"))
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(TURN, (prop, human, on[0], False, "settings.manage"))
        assert refused.value.sqlstate == "55000"
        assert refused.value.diag.message_primary == "At least one Refund Method stays on"
        connection.rollback()


@pytest.mark.parametrize(
    ("isolation", "answer"),
    [
        (psycopg.IsolationLevel.READ_COMMITTED, "55000"),
        (psycopg.IsolationLevel.REPEATABLE_READ, "40001"),
    ],
)
def test_two_people_turning_off_the_last_two_methods_at_once_leave_one_on(
    migrated_database_url: str,  # noqa: F811
    others_back_on: list[UUID],
    isolation: psycopg.IsolationLevel,
    answer: str,
) -> None:
    """The test adds its own two methods; the other methods that are on (seeded ones included)
    are turned off for the test only and turned on again after it."""
    human, prop, _, _ = source(migrated_database_url)
    settings = actor(human, prop, "settings.manage")
    first, second = uuid4(), uuid4()
    for method in (first, second):
        service().add_refund_method(
            prop, AddRefundMethodCommand(method, code(), "Wing money transfer"), actor=settings
        )
    with psycopg.connect(runtime_database_url()) as connection:
        rest = [
            UUID(str(row[0]))
            for row in connection.execute(
                "SELECT (item->>'id') FROM jsonb_array_elements("
                "app.list_refund_methods(%s,%s)->'items') item "
                "WHERE (item->>'active')::boolean AND (item->>'id')::uuid NOT IN (%s,%s)",
                (prop, human, first, second),
            ).fetchall()
        ]
    for method in rest:
        others_back_on.append(method)
        service().set_refund_method_on(prop, method, False, actor=settings)

    holder = psycopg.connect(runtime_database_url())
    try:
        holder.execute(TURN, (prop, human, first, False, "settings.manage"))

        def second_off() -> str:
            with psycopg.connect(runtime_database_url()) as other:
                other.isolation_level = isolation
                try:
                    other.execute(TURN, (prop, human, second, False, "settings.manage"))
                except psycopg.Error as exc:
                    return str(exc.sqlstate)
                return "changed"

        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(second_off)
            time.sleep(1)
            assert not waiting.done()
            holder.commit()
            assert waiting.result(timeout=10) == answer
    finally:
        holder.close()
    others_back_on.append(first)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refund_methods WHERE active"
        ).fetchone() == (1,)
