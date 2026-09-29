"""Real read-only preview services, dated posting and historical replay continuity."""

import os
import re
from copy import deepcopy
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from property_rental.allocation_read import AllocationReadService
from property_rental.credit import (
    ApplyCreditCommand,
    CreditAuthorizationError,
    CreditConflictError,
    CreditNotFoundError,
    CustomerCreditService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationNotFoundError,
    PaymentAllocationService,
    PostAllocationsCommand,
)
from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_financial_snapshot,
    position,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_due_posting_migration import recorded
from test_invoice_due_preview_wrappers_migration import intent_for, target_for
from test_invoice_due_proposal_migration import Context, funds
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _url_with_database
from test_reservation_migration import migrated_database_url as migrated_database_url

KINDS = ["PAYMENT", "CREDIT"]


def service_urls() -> tuple[str, str]:
    """Bind existing test-role URLs to the fixture's actual owned database."""
    target = conninfo_to_dict(os.environ["MIGRATION_DATABASE_URL"])
    name = target.get("dbname")
    assert isinstance(name, str) and re.fullmatch(r"prm(?:_due_legacy_[a-f0-9]{32})?", name)
    return (
        _url_with_database(runtime_database_url(), name),
        _url_with_database(financial_database_url(), name),
    )


def staff(
    kind: str,
    context: Context,
    *,
    actor: UUID | None = None,
    scope: UUID | None = None,
    permitted: bool = True,
) -> AuthenticatedActor:
    identity, prop, _, _, _ = context
    capability = "payments.allocate" if kind == "PAYMENT" else "credits.apply"
    return AuthenticatedActor(
        str(actor or identity),
        frozenset(
            [CapabilityGrant(capability, frozenset({str(scope or prop)}))] if permitted else []
        ),
    )


def preview(
    kind: str,
    context: Context,
    money: UUID,
    intent: dict[str, Any],
    actor: AuthenticatedActor | None = None,
) -> dict[str, Any]:
    who = actor or staff(kind, context)
    runtime, financial = service_urls()
    if kind == "PAYMENT":
        return AllocationReadService(runtime).designation_preview(
            context[1], money, intent, actor=who
        )
    return CustomerCreditService(runtime, financial).application_preview(
        context[1], money, intent, actor=who
    )


def post(
    kind: str, context: Context, money: UUID, intent: dict[str, Any], key: UUID
) -> dict[str, Any]:
    runtime, financial = service_urls()
    if kind == "PAYMENT":
        return PaymentAllocationService(runtime, financial).post(
            context[1], money, PostAllocationsCommand(key, intent), actor=staff(kind, context)
        )
    return CustomerCreditService(runtime, financial).apply(
        context[1], money, ApplyCreditCommand(key, intent), actor=staff(kind, context)
    )


@pytest.fixture
def preview_runtime_observations(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Observe actual driver connections; never replace database outcomes or SQL."""
    observations: list[dict[str, object]] = []
    original = psycopg.connect

    class ObservedRuntime:
        def __init__(self, connection: DB) -> None:
            self.connection = connection

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

        def __enter__(self) -> "ObservedRuntime":
            self.connection.__enter__()
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.connection.__exit__(*args)

        def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
            if query in (
                "SELECT app.payment_allocation_designation_preview(%s,%s,%s,%s)",
                "SELECT app.credit_application_designation_preview(%s,%s,%s,%s)",
            ):
                expected = conninfo_to_dict(os.environ["MIGRATION_DATABASE_URL"])
                port = expected.get("port")
                assert isinstance(port, (str, int)) and not isinstance(port, bool)
                assert self.connection.info.host == expected["host"] == "127.0.0.1"
                assert self.connection.info.port == int(port)
                assert self.connection.info.dbname == expected["dbname"]
                row = self.connection.execute(
                    "SELECT current_user,current_database(),"
                    "current_setting('transaction_read_only'),"
                    "current_setting('transaction_isolation'),current_setting('lock_timeout'),"
                    "current_setting('statement_timeout'),current_setting('TimeZone'),"
                    "to_regprocedure('app.payment_allocation_designation_preview"
                    "(uuid,uuid,uuid,jsonb)') IS NOT NULL,"
                    "to_regprocedure('app.credit_application_designation_preview"
                    "(uuid,uuid,uuid,jsonb)') IS NOT NULL"
                ).fetchone()
                assert row == (
                    "prm_runtime",
                    expected["dbname"],
                    "on",
                    "repeatable read",
                    "3s",
                    "5s",
                    "UTC",
                    True,
                    True,
                )
                observations.append(
                    {
                        "database": self.connection.info.dbname,
                        "role": self.connection.info.user,
                        "host": self.connection.info.host,
                        "port": self.connection.info.port,
                        "read_only": True,
                        "repeatable_read": True,
                        "lock_timeout_ms": 3000,
                        "statement_timeout_ms": 5000,
                        "utc": True,
                        "wrappers_visible": True,
                    }
                )
            return self.connection.execute(query, *args, **kwargs)

    def connect(conninfo: str = "", **kwargs: Any) -> Any:
        connection = original(conninfo, **kwargs)
        return ObservedRuntime(connection) if conninfo == service_urls()[0] else connection

    monkeypatch.setattr(psycopg, "connect", connect)
    return observations


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("explicit", [False, True])
def test_due_service_preview_posts_dated_parts_and_replays_exactly(
    due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
    explicit: bool,
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    intent = intent_for(kind, invoice, line)
    if explicit:
        target_for(kind, intent)["details"][0]["source_parts"] = [
            {"source_kind": "ORIGINAL_LINE", "source_id": str(line), "amount_usd_cents": 100}
        ]
    original = deepcopy(intent)
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    value = preview(kind, context, money, intent)
    assert intent == original and legacy_financial_snapshot(due_connection) == before
    assert len(preview_runtime_observations) == 1
    assert value["property_id"] == str(prop)
    assert value["payment_id" if kind == "PAYMENT" else "credit_id"] == str(money)
    prepared = value["intent"]
    parts = target_for(kind, prepared)["details"][0]["due_attribution"]["parts"]
    assert [(p["source_id"], p["amount_usd_cents"]) for p in parts] == (
        [(str(line), 100)] if explicit else [(str(debit), 50), (str(line), 50)]
    )
    key = uuid4()
    result = post(kind, context, money, prepared, key)
    assert [(str(x[2]), x[3]) for x in recorded(due_connection, kind, line)] == [
        (p["source_id"], p["amount_usd_cents"]) for p in parts
    ]
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 79950
    posted = legacy_financial_snapshot(due_connection)
    assert post(kind, context, money, prepared, key) == result
    assert legacy_financial_snapshot(due_connection) == posted


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["unknown", "disabled"])
def test_due_service_preview_rechecks_active_human_in_current_database(
    due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
    case: str,
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor = context[0]
    if case == "disabled":
        due_connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (actor,)
        )
    else:
        actor = uuid4()
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    error = AllocationAuthorizationError if kind == "PAYMENT" else CreditAuthorizationError
    with pytest.raises(error):
        preview(
            kind,
            context,
            money,
            intent_for(kind, context[-2], context[-1]),
            staff(kind, context, actor=actor),
        )
    assert len(preview_runtime_observations) == 1
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["missing", "wrong_property"])
def test_due_service_preview_denies_capability_before_runtime_connection(
    due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
    case: str,
) -> None:
    context, money = funds(due_connection, kind, 100)
    due_connection.commit()
    who = staff(
        kind,
        context,
        permitted=case != "missing",
        scope=uuid4() if case == "wrong_property" else None,
    )
    error = AllocationAuthorizationError if kind == "PAYMENT" else CreditAuthorizationError
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(error):
        preview(kind, context, money, intent_for(kind, context[-2], context[-1]), who)
    assert preview_runtime_observations == []
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_service_stale_preview_rejects_post_without_partial_effects(
    due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    due_connection.commit()
    value = preview(kind, context, money, intent_for(kind, invoice, line))
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    error = AllocationConflictError if kind == "PAYMENT" else CreditConflictError
    with pytest.raises(error):
        post(kind, context, money, value["intent"], uuid4())
    assert len(preview_runtime_observations) == 1
    assert recorded(due_connection, kind, line) == []
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_service_missing_source_maps_not_found_without_effects(
    due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
) -> None:
    context, _ = funds(due_connection, kind, 100)
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    error = AllocationNotFoundError if kind == "PAYMENT" else CreditNotFoundError
    with pytest.raises(error):
        preview(kind, context, uuid4(), intent_for(kind, context[-2], context[-1]))
    assert len(preview_runtime_observations) == 1
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_service_legacy_replay_survives_upgrade_without_rewriting(
    legacy_due_connection: DB,
    preview_runtime_observations: list[dict[str, object]],
    kind: str,
) -> None:
    context, money = funds(legacy_due_connection, kind, 200)
    intent = intent_for(kind, context[-2], context[-1])
    original = deepcopy(intent)
    legacy_due_connection.commit()
    key = uuid4()
    first = post(kind, context, money, intent, key)
    before = upgrade_populated_due_history(legacy_due_connection)
    assert post(kind, context, money, intent, key) == first
    assert intent == original and legacy_financial_snapshot(legacy_due_connection) == before
    value = preview(kind, context, money, intent)
    assert value["available_usd_cents"] == 100
    assert value["amount_usd_cents"] == 100 and value["part_count"] == 1
    assert len(preview_runtime_observations) == 1
    assert legacy_financial_snapshot(legacy_due_connection) == before
    assert legacy_due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts"
    ).fetchone() == (0,)
