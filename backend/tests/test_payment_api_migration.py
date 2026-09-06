"""Real isolated PostgreSQL HTTP wiring and immutable Payment evidence."""

from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr

from property_rental.app import create_app
from property_rental.configuration_api import ExchangeRateSourceUnavailable
from property_rental.identity import AuthenticatedActor
from property_rental.payment_api import Confirmation
from property_rental.settings import Settings
from test_credit_migration import actor
from test_invoice import mutation_headers
from test_invoice_migration import financial_database_url, runtime_database_url
from test_khr_payment_confirmation import Provider
from test_khr_payment_confirmation_migration import source as khr_source
from test_migrations import _temporary_migration_database
from test_payment_confirmation_migration import source
from test_payment_migration import fx_payment, reverse
from test_reservation_migration import migrated_database_url  # noqa: F401


def api(who: AuthenticatedActor, selected: Provider | None = None) -> TestClient:
    client = TestClient(
        create_app(
            Settings(
                database_url=SecretStr(runtime_database_url()),
                financial_database_url=SecretStr(financial_database_url()),
            ),
            actor_resolver=lambda _: who,
            exchange_rate_provider=selected,
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


@pytest.mark.parametrize("currency", ["USD", "KHR"])
def test_payment_http_real_confirmation_replay_read_and_preserved_receipt_fx_history(
    migrated_database_url: str,  # noqa: F811
    currency: str,
) -> None:
    human, prop, _, usd = source(migrated_database_url)
    request: Confirmation
    selected = None
    if currency == "KHR":
        human, prop, khr, selected = khr_source(migrated_database_url)
        request = khr
    else:
        request = usd
    # Retire only this test's own configured method; do not mutate a shared
    # synthetic fixture used by unrelated migration tests.
    method = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.payment_methods(id,code,display_name,accepted,created_by,updated_by) "
            "VALUES (%s,%s,'Original API method',true,%s,%s)",
            (method, f"API-{method}", human, human),
        )
    request = replace(request, payment_method_id=method)
    body: dict[str, object] = {
        "amount": {"currency": currency, "minor_units": request.received_amount_minor},
        "payer_customer_id": str(request.payer_customer_id),
        "payment_method_id": str(request.payment_method_id),
        "received_at": request.received_at.isoformat(),
        "evidence_reference": request.evidence_reference,
        "payer_intent_memo": request.payer_intent_memo,
        "channel_transaction_reference": request.channel_transaction_reference,
    }
    if currency == "KHR":
        body["usd_accounting_amount"] = {"currency": "USD", "minor_units": khr.usd_amount_cents}
    who = actor(human, prop, "payments.record", "payments.read")
    client = api(who, selected)
    headers = {**mutation_headers(key=request.idempotency_key), "X-Billing-Actor-ID": str(human)}
    path = f"/api/v1/properties/{prop}/payments"
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 201, first.text
    result = first.json()["data"]
    payment = result["payment"]
    identity = UUID(payment["id"])
    assert first.headers["Location"] == f"/api/v1/payments/{identity}"
    assert payment["received_currency"] == currency and payment["status"] == "RECEIVED"
    assert payment["received_amount_minor"] == request.received_amount_minor
    assert result["evidence_reference"] == request.evidence_reference
    assert result["receipt"]["payment_id"] == payment["id"]
    original = client.get(f"/api/v1/payments/{identity}")
    assert original.status_code == 200
    assert original.json()["data"]["payment"] == payment
    assert original.json()["data"]["confirmation_evidence"] == {
        "received_at": request.received_at.isoformat(),
        "evidence_reference": request.evidence_reference,
    }
    listed = client.get(path, params={"customer_id": str(request.payer_customer_id), "limit": "1"})
    assert listed.status_code == 200 and len(listed.json()["data"]) == 1
    assert (
        listed.json()["data"][0]["confirmation_evidence"]
        == original.json()["data"]["confirmation_evidence"]
    )
    assert listed.json()["page"]["next_cursor"] is None
    assert client.post(path, json=body, headers=headers).json()["data"] == result
    if selected is not None:
        assert selected.calls == 1
        assert (
            result["exchange_rate_record"]["calculation_trace"]["payable_khr"]
            == request.received_amount_minor
        )
        assert (
            original.json()["data"]["exchange_rate_evidence_id"]
            == payment["exchange_rate_record_id"]
        )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.payment_methods SET accepted=false,display_name='Retired API method' "
            "WHERE id=%s",
            (request.payment_method_id,),
        )
        for table in ("payment_allocations", "deposit_receipts"):
            assert connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM app.{} WHERE payment_id=%s").format(
                    psycopg.sql.Identifier(table)
                ),
                (identity,),
            ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (identity,)
        ).fetchone() == (1,)
        reverse(connection, identity, human)
    replay = client.post(path, json=body, headers=headers)
    assert replay.status_code == 201 and replay.json()["data"] == result
    detail = client.get(f"/api/v1/payments/{identity}").json()["data"]
    assert (
        detail["payment"]["status"] == "REVERSED" and detail["position"]["available_usd_cents"] == 0
    )
    assert (
        detail["payment"]["payment_method_name_snapshot"] == payment["payment_method_name_snapshot"]
    )
    assert detail["receipt"]["id"] == result["receipt"]["id"]
    conflict = client.post(
        path, json={**body, "evidence_reference": "Changed input"}, headers=headers
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )


def test_payment_http_real_scope_and_fresh_disabled_actor_fail_closed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, request = source(migrated_database_url)
    who = actor(human, prop, "payments.record", "payments.read")
    client = api(who)
    body = {
        "amount": {"currency": "USD", "minor_units": request.received_amount_minor},
        "payer_customer_id": str(request.payer_customer_id),
        "payment_method_id": str(request.payment_method_id),
        "received_at": request.received_at.isoformat(),
        "evidence_reference": request.evidence_reference,
    }
    path = f"/api/v1/properties/{prop}/payments"
    result = client.post(path, json=body, headers=mutation_headers())
    assert result.status_code == 201
    identity = result.json()["data"]["payment"]["id"]
    assert (
        api(actor(human, uuid4(), "payments.read")).get(f"/api/v1/payments/{identity}").status_code
        == 404
    )
    assert (
        api(actor(human, prop, "payments.record")).get(f"/api/v1/payments/{identity}").status_code
        == 404
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    assert client.get(f"/api/v1/payments/{identity}").status_code == 404
    assert client.get(path).status_code == 403
    assert client.post(path, json=body, headers=mutation_headers()).status_code == 403


def test_payment_http_real_khr_outage_fallback_permission_and_provider_recovery(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, request, selected = khr_source(migrated_database_url)
    body = {
        "amount": {"currency": "KHR", "minor_units": request.received_amount_minor},
        "usd_accounting_amount": {"currency": "USD", "minor_units": request.usd_amount_cents},
        "payer_customer_id": str(request.payer_customer_id),
        "payment_method_id": str(request.payment_method_id),
        "received_at": request.received_at.isoformat(),
        "evidence_reference": request.evidence_reference,
        "manual_reference": {
            "reference_rate_khr_per_usd": "4062.000000",
            "source_reference": "verified source",
            "applicable_at": request.received_at.isoformat(),
            "fallback_reason": "verified outage",
        },
    }
    path = f"/api/v1/properties/{prop}/payments"
    denied = api(actor(human, prop, "payments.record"), selected)
    assert denied.post(path, json=body, headers=mutation_headers()).status_code == 403
    assert selected.calls == 0
    client = api(actor(human, prop, "payments.record", "exchange_rates.manage"), selected)
    # Existing accepted service treats the available source as a current-state
    # conflict, not malformed fallback evidence. Keep its strict rejection.
    assert client.post(path, json=body, headers=mutation_headers()).status_code == 409
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (0,)
    selected.error = ExchangeRateSourceUnavailable("synthetic approved source unavailable")
    key = mutation_headers()
    success = client.post(path, json=body, headers=key)
    assert success.status_code == 201, success.text
    saved = success.json()["data"]
    assert saved["exchange_rate_record"]["entered_by"] == str(human)
    selected.error = None
    selected.quote = replace(selected.quote, source_reference="recovered source")
    before = selected.calls
    assert client.post(path, json=body, headers=key).json()["data"] == saved
    assert selected.calls == before
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (1,)


def test_payment_http_real_evidence_view_upgrade_preserves_history_and_hides_keys() -> None:
    with _temporary_migration_database("prm_payment_http_history") as url:
        config = Config("alembic.ini")
        alembic_command.upgrade(config, "20260906_43")
        snapshot = (
            "SELECT to_jsonb(p),to_jsonb(r),to_jsonb(fx) FROM app.payments p "
            "JOIN app.receipts r ON r.payment_id=p.id JOIN app.exchange_rate_records fx "
            "ON fx.id=p.exchange_rate_record_id WHERE p.id=%s"
        )
        with psycopg.connect(url) as connection:
            identity = fx_payment(connection)
            original = connection.execute(snapshot, (identity,)).fetchone()
            assert original is not None
        alembic_command.upgrade(config, "head")
        with psycopg.connect(url) as connection:
            assert connection.execute(snapshot, (identity,)).fetchone() == original
            assert connection.execute(
                "SELECT received_at,evidence_reference FROM app.payment_receipt_evidence "
                "WHERE payment_id=%s",
                (identity,),
            ).fetchone() == (None, None)
            assert connection.execute(
                "SELECT count(*) FROM app.payment_confirmation_commands"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='app' AND table_name='payment_receipt_evidence' "
                "ORDER BY ordinal_position"
            ).fetchall() == [
                ("payment_id",),
                ("property_id",),
                ("received_at",),
                ("evidence_reference",),
            ]
            assert connection.execute(
                "SELECT reloptions FROM pg_class WHERE oid='app.payment_receipt_evidence'::regclass"
            ).fetchone() == (["security_barrier=true"],)
            assert connection.execute(
                "SELECT is_updatable FROM information_schema.views "
                "WHERE table_schema='app' AND table_name='payment_receipt_evidence'"
            ).fetchone() == ("NO",)
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.payment_receipt_evidence','SELECT'), "
                    "has_table_privilege(%s,'app.payment_receipt_evidence',"
                    "'INSERT,UPDATE,DELETE,TRUNCATE'), "
                    "has_table_privilege(%s,'app.payment_confirmation_commands','SELECT')",
                    (role, role, role),
                ).fetchone() == (role != "prm_bootstrap", False, False)
        revision = ScriptDirectory.from_config(config).get_revision("20260907_44")
        assert revision is not None and revision.down_revision == "20260906_43"
        with pytest.raises(RuntimeError, match="forward-only"):
            revision.module.downgrade()
