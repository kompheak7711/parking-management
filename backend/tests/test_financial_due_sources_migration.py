"""Real dated-source HTTP reads, coherent pagination and legacy attribution conflicts."""

import os
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from property_rental.app import create_app
from property_rental.financial_due_sources import (
    FinancialDueSourcesRequest,
    FinancialDueSourcesService,
)
from property_rental.financial_reference import _ACTIVE_ACTOR
from property_rental.payment_read import PaymentReadAuthorizationError
from property_rental.settings import Settings
from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_adjustment,
    legacy_financial_snapshot,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_due_preview_service_migration import service_urls, staff
from test_invoice_due_proposal_migration import Context, funds
from test_reservation_migration import migrated_database_url as migrated_database_url

KINDS = ["PAYMENT", "CREDIT"]
Observations = dict[str, list[dict[str, object]]]


def parameters(kind: str, context: Context, money: UUID) -> dict[str, str]:
    return {
        "purpose": "allocation" if kind == "PAYMENT" else "credit_application",
        "source_id": str(money),
        "invoice_id": str(context[-2]),
        "invoice_line_id": str(context[-1]),
        "limit": "1",
    }


def client(kind: str, context: Context) -> TestClient:
    who = staff(kind, context)
    return TestClient(
        create_app(Settings(database_url=service_urls()[0]), actor_resolver=lambda _: who)
    )


def path(context: Context) -> str:
    return f"/api/v1/properties/{context[1]}/financial-due-sources"


def headers(context: Context) -> dict[str, str]:
    return {"X-Billing-Actor-ID": str(context[0]), "X-Financial-Property-ID": str(context[1])}


@pytest.fixture
def source_service_observations(monkeypatch: pytest.MonkeyPatch) -> Observations:
    """Observe actual connections and settings while delegating all real SQL unchanged."""
    observations: Observations = {"connections": [], "reads": []}
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
            if query == _ACTIVE_ACTOR:
                target = conninfo_to_dict(os.environ["MIGRATION_DATABASE_URL"])
                port = target.get("port")
                assert isinstance(port, (str, int)) and not isinstance(port, bool)
                assert self.connection.info.host == target["host"] == "127.0.0.1"
                assert self.connection.info.port == int(port)
                assert self.connection.info.dbname == target["dbname"]
                row = self.connection.execute(
                    "SELECT current_user,current_database(),"
                    "current_setting('transaction_read_only'),"
                    "current_setting('transaction_isolation'),current_setting('lock_timeout'),"
                    "current_setting('statement_timeout'),current_setting('TimeZone'),"
                    "to_regprocedure('app.financial_invoice_due_sources_page"
                    "(uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid)') IS NOT NULL"
                ).fetchone()
                assert row == (
                    "prm_runtime",
                    target["dbname"],
                    "on",
                    "repeatable read",
                    "3s",
                    "5s",
                    "UTC",
                    True,
                )
                observations["reads"].append(
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
                        "wrapper_visible": True,
                        "fresh_actor_query": True,
                    }
                )
            return self.connection.execute(query, *args, **kwargs)

    def connect(conninfo: str = "", **kwargs: Any) -> Any:
        connection = original(conninfo, **kwargs)
        if connection.info.user != "prm_runtime":
            return connection
        observations["connections"].append(
            {
                "database": connection.info.dbname,
                "role": connection.info.user,
                "host": connection.info.host,
                "port": connection.info.port,
            }
        )
        return ObservedRuntime(connection)

    monkeypatch.setattr(psycopg, "connect", connect)
    return observations


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_http_pages_preserve_live_dated_facts(
    due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    first = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    last = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 70, date(2027, 3, 1))
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    params = parameters(kind, context, money)
    rows: list[dict[str, Any]] = []
    revisions: list[str] = []
    with client(kind, context) as web:
        for index in range(3):
            response = web.get(path(context), params=params, headers=headers(context))
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "private, no-store"
            assert "Cookie" in response.headers["Vary"]
            body = response.json()
            assert body["meta"] == {
                "property_id": str(prop),
                "actor_id": str(actor),
                "request_id": response.headers["X-Request-ID"],
            }
            data = body["data"]
            assert data["source_id"] == str(money) and data["invoice_id"] == str(invoice)
            assert (
                data["invoice_line_id"] == str(line)
                and data["aggregate_outstanding_usd_cents"] == 80120
            )
            assert data["item_count"] == 3 and len(data["items"]) == 1
            rows.extend(data["items"])
            revisions.append(data["revision"])
            continuation = body["page"]["next_cursor"]
            if index < 2:
                assert isinstance(continuation, str)
                params["cursor"] = continuation
            else:
                assert continuation is None
    assert len(set(revisions)) == 1
    assert [(x["source_id"], x["approved_due_date"], x["remaining_usd_cents"]) for x in rows] == [
        (str(first), "2027-01-01", 50),
        (str(line), "2027-02-05", 80000),
        (str(last), "2027-03-01", 70),
    ]
    assert legacy_financial_snapshot(due_connection) == before
    assert (
        len(source_service_observations["connections"])
        == len(source_service_observations["reads"])
        == 3
    )


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_http_stale_page_requires_reload(
    due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    due_connection.commit()
    params = parameters(kind, context, money)
    with client(kind, context) as web:
        first = web.get(path(context), params=params, headers=headers(context))
        assert first.status_code == 200
        continuation = first.json()["page"]["next_cursor"]
        assert isinstance(continuation, str)
        params["cursor"] = continuation
        adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 70, date(2027, 3, 1))
        due_connection.commit()
        before = legacy_financial_snapshot(due_connection)
        response = web.get(path(context), params=params, headers=headers(context))
    assert response.status_code == 409 and "data" not in response.json()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert legacy_financial_snapshot(due_connection) == before
    assert (
        len(source_service_observations["connections"])
        == len(source_service_observations["reads"])
        == 2
    )


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_service_denies_capability_before_connection(
    due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    request = FinancialDueSourcesRequest(
        parameters(kind, context, money)["purpose"], money, context[-2], context[-1]
    )
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(PaymentReadAuthorizationError):
        FinancialDueSourcesService(service_urls()[0]).get(
            context[1], request, actor=staff(kind, context, permitted=False)
        )
    assert legacy_financial_snapshot(due_connection) == before
    assert source_service_observations == {"connections": [], "reads": []}


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_http_rechecks_current_active_actor(
    due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    due_connection.execute(
        "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (context[0],)
    )
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    with client(kind, context) as web:
        response = web.get(
            path(context), params=parameters(kind, context, money), headers=headers(context)
        )
    assert response.status_code == 403 and "data" not in response.json()
    assert legacy_financial_snapshot(due_connection) == before
    assert (
        len(source_service_observations["connections"])
        == len(source_service_observations["reads"])
        == 1
    )


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_http_missing_source_stays_scoped(
    due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, _ = funds(due_connection, kind, 100)
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    missing = uuid4()
    with client(kind, context) as web:
        response = web.get(
            path(context), params=parameters(kind, context, missing), headers=headers(context)
        )
    assert response.status_code == 404 and "data" not in response.json()
    assert str(missing) not in response.text
    assert legacy_financial_snapshot(due_connection) == before
    assert (
        len(source_service_observations["connections"])
        == len(source_service_observations["reads"])
        == 1
    )


@pytest.mark.parametrize("kind", KINDS)
def test_due_source_http_legacy_attribution_conflict(
    legacy_due_connection: DB, source_service_observations: Observations, kind: str
) -> None:
    context, money = funds(legacy_due_connection, kind, 100)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 50)
    before = upgrade_populated_due_history(legacy_due_connection)
    with client(kind, context) as web:
        response = web.get(
            path(context), params=parameters(kind, context, money), headers=headers(context)
        )
    assert response.status_code == 409 and "data" not in response.json()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert legacy_financial_snapshot(legacy_due_connection) == before
    assert (
        len(source_service_observations["connections"])
        == len(source_service_observations["reads"])
        == 1
    )
