"""Runtime-role references and provisional preview on isolated synthetic PostgreSQL."""

from collections.abc import Callable
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.financial_reference import FinancialReferenceService, ReferencePage
from property_rental.payment_read import PaymentReadAuthorizationError, PaymentReadNotFoundError
from test_credit_migration import actor
from test_invoice_migration import runtime_database_url
from test_khr_payment_confirmation import provider
from test_reservation_migration import (  # noqa: F401
    migrated_database_url,
    setup_reservation_sources,
)


def test_financial_reference_runtime_pages_keep_method_identities_and_skip_retired(
    migrated_database_url: str,  # noqa: F811
) -> None:
    prefix = str(uuid4())
    ids = [uuid4() for _ in range(105)]
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_reservation_sources(connection)
        baseline = connection.execute(
            "SELECT id FROM app.payment_methods WHERE accepted ORDER BY id"
        ).fetchall()
        for index, identity in enumerate(ids):
            connection.execute(
                "INSERT INTO app.payment_methods"
                "(id,code,display_name,accepted,created_by,updated_by) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    identity,
                    f"{prefix}-{index}",
                    "Legacy label " + "x" * (3000 if index == 0 else 1),
                    index != 104,
                    human,
                    human,
                ),
            )
        expected = connection.execute(
            "SELECT id,code,display_name FROM app.payment_methods WHERE accepted ORDER BY id"
        ).fetchall()
    try:
        service = FinancialReferenceService(runtime_database_url())
        current = actor(human, prop, "payments.record")
        observed: list[dict[str, object]] = []
        after = None
        for _ in range(len(expected) + 1):
            result = service.methods(prop, ReferencePage(7, after), actor=current)
            page = cast(list[dict[str, object]], result["items"])
            assert len(page) <= 7 and all(item["property_id"] == str(prop) for item in page)
            observed.extend(page)
            cursor = result["next_cursor"]
            if cursor is None:
                break
            assert page and cursor == page[-1]["id"]
            after = UUID(str(cursor))
        assert [(item["id"], item["code"], item["display_name"]) for item in observed] == [
            (str(row[0]), row[1], row[2]) for row in expected
        ]
        assert str(ids[104]) not in {item["id"] for item in observed}
        workspaces = service.workspaces(ReferencePage(1), actor=current)
        work = cast(list[dict[str, object]], workspaces["items"])
        assert len(work) == 1 and work[0]["property_id"] == str(prop)
        assert work[0]["timezone"] == "Asia/Phnom_Penh"
        assert (
            service.workspaces(ReferencePage(), actor=actor(human, prop, "property.manage"))[
                "items"
            ]
            == []
        )
        view = service.capability_view(prop, actor=current)
        assert cast(dict[str, bool], view["capabilities"])["payments.record"] is True
        assert cast(dict[str, bool], view["capabilities"])["payments.read"] is False
    finally:
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.payment_methods SET accepted=false,updated_at=statement_timestamp(),"
                "updated_by=%s WHERE id=ANY(%s::uuid[])",
                (human, ids),
            )
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT id FROM app.payment_methods WHERE accepted ORDER BY id"
            ).fetchall()
            == baseline
        )


def test_financial_reference_runtime_preview_has_no_persistent_financial_effects(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_reservation_sources(connection)
    source = provider()
    service = FinancialReferenceService(runtime_database_url(), source)

    # Compare every app table, including command/idempotency/FX/Receipt/guard rows.
    # The isolated test cluster is synthetic; no source/production data is accessed.
    def snapshot() -> dict[str, int]:
        with psycopg.connect(migrated_database_url) as connection:
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename"
            ).fetchall()
            return {
                str(row[0]): cast(
                    tuple[int],
                    connection.execute(
                        psycopg.sql.SQL("SELECT count(*) FROM app.{}").format(
                            psycopg.sql.Identifier(str(row[0]))
                        )
                    ).fetchone(),
                )[0]
                for row in tables
            }

    before = snapshot()
    for _ in range(2):
        result = service.preview(prop, 1001, None, actor=actor(human, prop, "payments.record"))
        assert result["payable_khr_amount"] == 40871 and result["provisional"] is True
    assert source.calls == 2 and snapshot() == before


def test_financial_reference_runtime_denies_missing_property_actor_and_disabled_actor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_reservation_sources(connection)
    source = provider()
    service = FinancialReferenceService(runtime_database_url(), source)
    missing = uuid4()
    with pytest.raises(PaymentReadNotFoundError):
        service.methods(missing, ReferencePage(), actor=actor(human, missing, "payments.record"))
    with pytest.raises(PaymentReadAuthorizationError):
        service.methods(prop, ReferencePage(), actor=actor(human, missing, "payments.record"))
    with pytest.raises(PaymentReadAuthorizationError):
        service.workspaces(ReferencePage(), actor=actor(uuid4(), prop, "payments.record"))
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    current = actor(human, prop, "payments.record")
    operations: list[Callable[[], dict[str, object]]] = [
        lambda: service.workspaces(ReferencePage(), actor=current),
        lambda: service.capability_view(prop, actor=current),
        lambda: service.methods(prop, ReferencePage(), actor=current),
        lambda: service.preview(prop, 100, None, actor=current),
    ]
    for operation in operations:
        with pytest.raises(PaymentReadAuthorizationError):
            operation()
    assert source.calls == 0
