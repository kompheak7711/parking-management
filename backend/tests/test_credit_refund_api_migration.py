"""Canonical Credit/USD Refund HTTP workflows on isolated real PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr

from property_rental.app import create_app
from property_rental.refund import RefundService
from property_rental.settings import Settings
from refund_test_support import cash, create_usd_refund
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, source
from test_credit_refund_read_migration import snapshot as read_snapshot
from test_invoice import mutation_headers
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _required_url, _temporary_migration_database, _url_with_database
from test_payment_api_migration import api
from test_refund_service_migration import returned
from test_reservation_migration import migrated_database_url  # noqa: F401

CAPABILITIES = (
    "credits.read",
    "credits.recognize",
    "credits.reverse",
    "credits.apply",
    "credits.applications.reverse",
    "refunds.read",
    "refunds.create",
    "refunds.correct",
    "refunds.corrections.reverse",
    "financial.approve",
)


def snapshot(url: str, payment: UUID) -> tuple[object, ...]:
    result = read_snapshot(url, payment)
    assert isinstance(result, tuple)
    return result


def headers(human: UUID, key: UUID | None = None) -> dict[str, str]:
    return {**mutation_headers(key=key), "X-Billing-Actor-ID": str(human)}


def post_refund(
    client: TestClient,
    prop: UUID,
    human: UUID,
    body: dict[str, object],
    headers: dict[str, str],
) -> Response:
    """V1-056 slice 3a: record the Refund draft, then confirm it under financial.approve."""
    choice = cash(
        RefundService(runtime_database_url(), financial_database_url()),
        prop,
        actor(human, prop, "refunds.read"),
    )
    draft: Response = client.post(
        "/api/v1/refund-drafts",
        json={
            **body,
            "refund_method_id": str(choice.refund_method_id),
            "reference_note": choice.reference_note,
        },
        headers=headers,
    )
    if draft.status_code != 201:
        return draft
    draft_id = draft.json()["data"]["draft_id"]
    confirmed: Response = client.post(
        f"/api/v1/properties/{prop}/refund-drafts/{draft_id}/confirm", headers=headers
    )
    return confirmed


def value(response: object, status: int = 200) -> dict[str, object]:
    from httpx import Response

    assert isinstance(response, Response)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    result = response.json()["data"]
    assert isinstance(result, dict)
    return cast(dict[str, object], result)


def test_credit_refund_http_real_recognition_read_pages_reverse_and_original_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    client = api(actor(human, prop, *CAPABILITIES))
    before = snapshot(migrated_database_url, payment)
    path = f"/api/v1/payments/{payment}/credit-recognitions"
    body = {
        "currency": "USD",
        "amount_usd_cents": 6000,
        "payer_authorization_reference": "Payer authorized retention",
        "reason": "Retain eligible excess",
    }
    first_headers = headers(human)
    first = value(client.post(path, json=body, headers=first_headers), 201)
    credit = UUID(str(cast(dict[str, object], first["credit"])["id"]))
    second = value(
        client.post(path, json={**body, "amount_usd_cents": 2000}, headers=headers(human)), 201
    )
    other = str(cast(dict[str, object], second["credit"])["id"])
    after_posts = snapshot(migrated_database_url, payment)
    assert before is not None and after_posts is not None
    assert before[:2] == after_posts[:2]
    credit_path = f"/api/v1/customer-credits/{credit}"
    assert value(client.get(credit_path)) == first
    listed = client.get(f"/api/v1/customers/{customer}/credits", params={"limit": "1"})
    assert listed.status_code == 200 and len(listed.json()["data"]) == 1
    following = client.get(
        f"/api/v1/customers/{customer}/credits",
        params={"limit": "1", "cursor": listed.json()["page"]["next_cursor"]},
    )
    assert following.status_code == 200 and following.json()["page"]["next_cursor"] is None
    rows = listed.json()["data"] + following.json()["data"]
    assert {row["credit"]["id"] for row in rows} == {str(credit), other}
    assert snapshot(migrated_database_url, payment) == after_posts
    reverse_body = {"reason": "Correct recognition"}
    reverse_headers = headers(human)
    reversed_result = value(
        client.post(credit_path + "/reverse", json=reverse_body, headers=reverse_headers)
    )
    assert reversed_result["available_usd_cents"] == 0
    assert value(client.post(path, json=body, headers=first_headers), 201) == first
    assert (
        value(client.post(credit_path + "/reverse", json=reverse_body, headers=reverse_headers))
        == reversed_result
    )
    assert value(client.get(credit_path)) == reversed_result
    ledger = value(client.get(credit_path + "/ledger", params={"limit": "1"}))
    history = cast(dict[str, object], ledger["history"])
    page = cast(dict[str, object], history["page"])
    following_ledger = value(
        client.get(
            credit_path + "/ledger", params={"limit": "1", "cursor": str(page["next_cursor"])}
        )
    )
    second_history = cast(dict[str, object], following_ledger["history"])
    events = cast(list[dict[str, object]], history["items"]) + cast(
        list[dict[str, object]], second_history["items"]
    )
    assert {event["event_kind"] for event in events} == {"RECOGNITION", "RECOGNITION_REVERSAL"}
    assert cast(dict[str, object], second_history["page"])["next_cursor"] is None
    conflict = client.post(path, json={**body, "reason": "Changed replay"}, headers=first_headers)
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )


def test_credit_refund_http_real_proposal_application_details_reversal_and_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, _, payment = application_source(migrated_database_url)
    client = api(actor(human, prop, *CAPABILITIES))
    path = f"/api/v1/customer-credits/{credit}"
    before = snapshot(migrated_database_url, payment)
    proposal = value(
        client.get(
            path + "/application-proposal",
            params={"invoice_id": str(invoice), "amount_usd_cents": "1000"},
        )
    )
    assert proposal["credit_id"] == str(credit) and proposal["invoice_id"] == str(invoice)
    assert snapshot(migrated_database_url, payment) == before

    body = {"currency": "USD", "intent": {"mode": "PROPOSAL", "proposal": proposal}}
    posted_headers = headers(human)
    posted = value(client.post(path + "/applications", json=body, headers=posted_headers), 201)
    application = UUID(str(cast(dict[str, object], posted["application"])["id"]))
    application_path = f"/api/v1/credit-applications/{application}"
    assert value(client.get(application_path)) == posted
    assert len(cast(list[object], posted["details"])) == 1
    assert cast(dict[str, object], posted["application"])["amount_usd_cents"] == 1000
    reverse_headers = headers(human)
    reverse_body = {"reason": "Correct application target"}
    reversed_result = value(
        client.post(application_path + "/reverse", json=reverse_body, headers=reverse_headers)
    )
    assert reversed_result["details"] == posted["details"]
    assert (
        cast(int, reversed_result["target_balance_usd_cents"])
        == cast(int, posted["target_balance_usd_cents"]) + 1000
    )
    assert (
        value(client.post(path + "/applications", json=body, headers=posted_headers), 201) == posted
    )
    assert (
        value(
            client.post(application_path + "/reverse", json=reverse_body, headers=reverse_headers)
        )
        == reversed_result
    )
    assert value(client.get(application_path)) == reversed_result


@pytest.mark.parametrize("currency", ["USD", "KHR"])
@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_credit_refund_http_real_usd_refund_return_reversal_original_fx_and_replays(
    migrated_database_url: str,  # noqa: F811
    currency: str,
    kind: str,
) -> None:
    from property_rental.khr_payment_confirmation import KhrPaymentConfirmationService
    from test_invoice_migration import financial_database_url
    from test_khr_payment_confirmation_migration import identity
    from test_khr_payment_confirmation_migration import source as khr_source

    if currency == "KHR":
        human, prop, request, provider = khr_source(migrated_database_url)
        confirmed = KhrPaymentConfirmationService(financial_database_url(), provider).confirm_khr(
            prop, request, actor=actor(human, prop, "payments.record")
        )
        payment = identity(confirmed)
        customer = request.payer_customer_id
    else:
        human, prop, customer, payment = source(migrated_database_url)
    source_id = credit_id(recognize(prop, payment, human, 600)) if kind == "CREDIT" else payment
    client = api(actor(human, prop, *CAPABILITIES))
    before = snapshot(migrated_database_url, payment)
    source_path = f"/api/v1/refund-sources/{kind}/{source_id}"
    available = value(client.get(source_path))
    assert available["refund_currency"] == "USD"
    audit_payment = cast(dict[str, object], available["source_payment"])
    assert audit_payment["received_currency"] == currency
    assert audit_payment["id"] == str(payment)
    assert snapshot(migrated_database_url, payment) == before
    body = {
        "currency": "USD",
        "source_type": kind,
        "source_id": str(source_id),
        "amount_usd_cents": 500,
        "reason": "Return eligible USD excess",
    }
    create_headers = headers(human)
    original = value(post_refund(client, prop, human, body, headers=create_headers), 201)
    refund = cast(dict[str, object], original["refund"])
    path = f"/api/v1/refunds/{refund['id']}"
    assert refund["refund_currency"] == "USD" and refund["refund_amount_minor"] == 500
    assert refund["recipient_customer_id"] == str(customer)
    assert value(client.get(path)) == original
    assert original["source_payment"] == available["source_payment"]
    assert original["source_exchange_rate"] == available["source_exchange_rate"]
    returned_command = returned(200)
    return_body = {
        "currency": "USD",
        "returned_amount_minor": 200,
        "returned_at": returned_command.returned_at.isoformat(),
        "return_method_reference": returned_command.return_method_reference,
        "evidence_reference": returned_command.evidence_reference,
        "reason": returned_command.reason,
    }
    return_headers = headers(human, returned_command.idempotency_key)
    corrected = value(
        client.post(path + "/verified-returns", json=return_body, headers=return_headers)
    )
    assert corrected["net_refund_usd_cents"] == 300
    corrections = cast(dict[str, object], corrected["corrections"])
    correction = cast(list[dict[str, object]], corrections["items"])[0]
    assert correction["verified_return_currency"] == "USD"
    assert correction["verified_return_amount_minor"] == 200
    reverse_path = path + f"/verified-returns/{correction['id']}/reverse"
    reverse_body = {
        "evidence_reference": "Verified correction review",
        "reason": "Reverse incorrect return",
    }
    reverse_headers = headers(human)
    reversed_result = value(client.post(reverse_path, json=reverse_body, headers=reverse_headers))
    assert reversed_result["net_refund_usd_cents"] == 500
    assert reversed_result["refund"] == original["refund"]
    assert value(post_refund(client, prop, human, body, headers=create_headers), 201) == original
    assert (
        value(client.post(path + "/verified-returns", json=return_body, headers=return_headers))
        == corrected
    )
    assert (
        value(client.post(reverse_path, json=reverse_body, headers=reverse_headers))
        == reversed_result
    )
    assert value(client.get(path)) == reversed_result
    listed = client.get(f"/api/v1/properties/{prop}/refunds", params={"customer_id": str(customer)})
    assert listed.status_code == 200 and len(listed.json()["data"]) == 1
    assert listed.json()["data"][0]["refund"] == original["refund"]
    page1 = cast(dict[str, object], value(client.get(path, params={"limit": "1"}))["corrections"])
    cursor = cast(dict[str, object], page1["page"])["next_cursor"]
    page2 = cast(
        dict[str, object],
        value(client.get(path, params={"limit": "1", "cursor": str(cursor)}))["corrections"],
    )
    assert len(cast(list[object], page1["items"])) == len(cast(list[object], page2["items"])) == 1
    assert cast(dict[str, object], page2["page"])["next_cursor"] is None
    remaining = value(client.get(source_path))
    assert remaining["available_usd_cents"] == cast(int, available["available_usd_cents"]) - 500
    assert remaining["source_payment"] == available["source_payment"]
    assert remaining["source_exchange_rate"] == available["source_exchange_rate"]


def test_credit_refund_http_real_pet_requires_matching_review_and_preserves_lease(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from test_pet_refund_migration import qualified

    human, prop, _, lease, deposit, review = qualified(migrated_database_url)
    client = api(actor(human, prop, *CAPABILITIES))
    path = f"/api/v1/refund-sources/PET_DEPOSIT/{deposit}"
    preview = value(client.get(path, params={"pet_refund_review_id": str(review)}))
    assert preview["refund_currency"] == "USD" and preview["pet_refund_review_id"] == str(review)
    assert client.get(path).status_code == 400
    assert client.get(path, params={"pet_refund_review_id": str(uuid4())}).status_code == 404
    body = {
        "currency": "USD",
        "source_type": "PET_DEPOSIT",
        "source_id": str(deposit),
        "pet_refund_review_id": str(review),
        "amount_usd_cents": 1000,
        "reason": "Qualified Pet exception",
    }
    request_headers = headers(human)
    result = value(post_refund(client, prop, human, body, headers=request_headers), 201)
    assert cast(dict[str, object], result["refund"])["pet_refund_review_id"] == str(review)
    assert value(post_refund(client, prop, human, body, headers=request_headers), 201) == result
    assert (
        post_refund(
            client,
            prop,
            human,
            {**body, "final_settlement_id": str(uuid4())},
            headers=headers(human),
        ).status_code
        == 422
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.leases WHERE id=%s", (lease,)
        ).fetchone() == ("SIGNED",)
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (1,)


def test_credit_refund_http_real_fresh_actor_scope_and_nul_denial_have_no_effects(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    who = actor(human, prop, *CAPABILITIES)
    client = api(who)
    path = f"/api/v1/payments/{payment}/credit-recognitions"
    body = {
        "currency": "USD",
        "amount_usd_cents": 1000,
        "payer_authorization_reference": "Payer consent",
        "reason": "Keep eligible excess",
    }
    before = snapshot(migrated_database_url, payment)
    assert (
        client.post(
            path, json={**body, "reason": "bad\x00text"}, headers=headers(human)
        ).status_code
        == 422
    )
    assert (
        api(actor(human, uuid4(), *CAPABILITIES))
        .post(path, json=body, headers=headers(human))
        .status_code
        == 404
    )
    assert (
        api(actor(human, prop, "credits.read"))
        .post(path, json=body, headers=headers(human))
        .status_code
        == 404
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    assert client.post(path, json=body, headers=headers(human)).status_code == 404
    assert client.get(f"/api/v1/refund-sources/PAYMENT/{payment}").status_code == 404
    assert snapshot(migrated_database_url, payment) == before


def test_credit_refund_http_real_runtime_reads_need_no_writer_and_never_fall_back(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 1000))
    who = actor(human, prop, *CAPABILITIES)
    client = TestClient(
        create_app(
            settings=Settings(
                database_url=SecretStr(runtime_database_url()), financial_database_url=None
            ),
            actor_resolver=lambda _: who,
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    before = snapshot(migrated_database_url, payment)
    assert value(client.get(f"/api/v1/customer-credits/{credit}"))["available_usd_cents"] == 1000
    assert (
        value(client.get(f"/api/v1/refund-sources/CREDIT/{credit}"))["available_usd_cents"] == 1000
    )
    body = {
        "currency": "USD",
        "source_type": "CREDIT",
        "source_id": str(credit),
        "amount_usd_cents": 500,
        "reason": "Authorized but no writer",
    }
    assert post_refund(client, prop, human, body, headers=headers(human)).status_code == 503
    assert (
        client.post(
            f"/api/v1/customer-credits/{credit}/reverse",
            json={"reason": "No writer"},
            headers=headers(human),
        ).status_code
        == 503
    )
    assert snapshot(migrated_database_url, payment) == before


@contextmanager
def _refund_competition_database(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Isolate success-path setup while retaining real competing Refund transactions."""
    names = ("MIGRATION_DATABASE_URL", "APP_DATABASE_URL", "FINANCIAL_DATABASE_URL")
    before = {name: _required_url(name) for name in names}
    original_database = urlsplit(migrated_database_url).path
    try:
        with _temporary_migration_database("prm_refund_competition") as migration_url:
            database = urlsplit(migration_url).path.removeprefix("/")
            assert "/" + database != original_database
            with monkeypatch.context() as environment:
                for name in ("APP_DATABASE_URL", "FINANCIAL_DATABASE_URL"):
                    environment.setenv(name, _url_with_database(before[name], database))
                command.upgrade(Config("alembic.ini"), "head")
                for name in names:
                    connection_url = _required_url(name).replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    )
                    with psycopg.connect(
                        connection_url,
                        connect_timeout=3,
                        autocommit=True,
                        options="-c default_transaction_read_only=on -c statement_timeout=1000",
                    ) as probe:
                        assert probe.execute(
                            "SELECT current_database()=%s, to_regclass('app.invoices') IS NOT NULL",
                            (database,),
                        ).fetchone() == (True, True)
                yield migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    finally:
        assert all(_required_url(name) == before[name] for name in names)


@pytest.fixture
def refund_competition_database_url(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    with _refund_competition_database(migrated_database_url, monkeypatch) as database_url:
        yield database_url


def test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit(
    refund_competition_database_url: str,
) -> None:
    from threading import Barrier

    human, prop, _, payment = source(refund_competition_database_url, 2000)
    credit = credit_id(recognize(prop, payment, human, 1000))
    clients = [api(actor(human, prop, *CAPABILITIES)) for _ in range(2)]
    request_headers = [headers(human), headers(human)]
    body = {
        "currency": "USD",
        "source_type": "CREDIT",
        "source_id": str(credit),
        "amount_usd_cents": 800,
        "reason": "Return eligible credit",
    }
    barrier = Barrier(2)

    def send(index: int) -> object:
        barrier.wait(timeout=10)
        return post_refund(clients[index], prop, human, body, headers=request_headers[index])

    from httpx import Response

    with ThreadPoolExecutor(max_workers=2) as pool:
        raw_responses = list(pool.map(send, [0, 1]))
    assert all(isinstance(result, Response) for result in raw_responses)
    responses = cast(list[Response], raw_responses)
    assert sum(result.status_code == 201 for result in responses) == 1
    # V1-056 sub-slice 8f: a check violation at confirmation answers 409 (the draft stays pending).
    assert all(result.status_code in {201, 409, 422, 503} for result in responses)
    winner = next(i for i, result in enumerate(responses) if result.status_code == 201)
    original = value(responses[winner], 201)
    assert (
        value(post_refund(clients[winner], prop, human, body, headers=request_headers[winner]), 201)
        == original
    )
    assert value(clients[0].get(f"/api/v1/customer-credits/{credit}"))["available_usd_cents"] == 200
    with psycopg.connect(refund_competition_database_url) as connection:
        assert connection.execute(
            "SELECT count(*),sum(usd_accounting_value_cents) FROM app.refunds "
            "WHERE source_customer_credit_id=%s",
            (credit,),
        ).fetchone() == (1, 800)


def test_credit_refund_competition_fixture_isolates_unrelated_shared_writer(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("MIGRATION_DATABASE_URL", "APP_DATABASE_URL", "FINANCIAL_DATABASE_URL")
    before = {name: _required_url(name) for name in names}
    with psycopg.connect(migrated_database_url) as writer:
        writer.execute("LOCK TABLE app.invoices IN ROW EXCLUSIVE MODE")
        with _refund_competition_database(migrated_database_url, monkeypatch) as isolated_url:
            assert urlsplit(isolated_url).path != urlsplit(migrated_database_url).path
            test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit(
                isolated_url
            )
        assert writer.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() "
            "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "AND relation='app.invoices'::regclass AND mode='RowExclusiveLock' AND granted)"
        ).fetchone() == (True,)
        assert all(_required_url(name) == before[name] for name in names)


def test_credit_refund_http_real_correction_identity_cannot_cross_refunds(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url, 2000)
    _, _, _, other_payment = source(migrated_database_url, 2000)
    client = api(actor(human, prop, *CAPABILITIES))
    results = []
    for source_id in (payment, other_payment):
        body = {
            "currency": "USD",
            "source_type": "PAYMENT",
            "source_id": str(source_id),
            "amount_usd_cents": 1000,
            "reason": "Eligible excess return",
        }
        results.append(value(post_refund(client, prop, human, body, headers=headers(human)), 201))
    refunds = [str(cast(dict[str, object], result["refund"])["id"]) for result in results]
    command = returned(100)
    body = {
        "currency": "USD",
        "returned_amount_minor": 100,
        "returned_at": command.returned_at.isoformat(),
        "return_method_reference": command.return_method_reference,
        "evidence_reference": command.evidence_reference,
        "reason": command.reason,
    }
    corrected = value(
        client.post(
            f"/api/v1/refunds/{refunds[0]}/verified-returns", json=body, headers=headers(human)
        )
    )
    corrections = cast(dict[str, object], corrected["corrections"])
    correction = cast(list[dict[str, object]], corrections["items"])[0]
    before = (
        snapshot(migrated_database_url, payment),
        snapshot(migrated_database_url, other_payment),
    )
    response = client.post(
        f"/api/v1/refunds/{refunds[1]}/verified-returns/{correction['id']}/reverse",
        json={"evidence_reference": "Wrong parent", "reason": "Must be rejected"},
        headers=headers(human),
    )
    assert response.status_code == 404
    assert (
        snapshot(migrated_database_url, payment),
        snapshot(migrated_database_url, other_payment),
    ) == before


def test_credit_refund_http_ledger_pages_preserve_all_seven_event_families(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from property_rental.credit import ReverseCreditApplicationCommand, ReverseCreditCommand
    from property_rental.refund import ReverseRefundCorrectionCommand
    from test_credit_application_migration import application_id, designated
    from test_credit_migration import service as credits
    from test_refund_service_migration import corrections, create, refund_id
    from test_refund_service_migration import service as refunds

    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    who = actor(human, prop, *CAPABILITIES)
    applied = credits().apply(prop, credit, designated(invoice, line, 30000), actor=who)
    paid = create_usd_refund(refunds(), prop, create(credit, 20000, "CREDIT"), actor=who)
    refund = refund_id(paid)
    partial = refunds().verify_usd_return(prop, refund, returned(5000), actor=who)
    refunds().reverse_correction(
        prop,
        refund,
        UUID(str(corrections(partial)[0]["id"])),
        ReverseRefundCorrectionCommand(uuid4(), "Verified review", "Wrong return"),
        actor=who,
    )
    refunds().verify_usd_return(prop, refund, returned(20000), actor=who)
    credits().reverse_application(
        prop,
        application_id(applied),
        ReverseCreditApplicationCommand(uuid4(), "Wrong target"),
        actor=who,
    )
    credits().reverse(prop, credit, ReverseCreditCommand(uuid4(), "Wrong consent"), actor=who)
    client = api(who)
    path = f"/api/v1/customer-credits/{credit}/ledger"
    before = snapshot(migrated_database_url, payment)
    full = value(client.get(path))
    expected = cast(list[dict[str, object]], cast(dict[str, object], full["history"])["items"])
    position = cast(dict[str, object], full["position"])
    assert position["recognized_usd_cents"] == position["reversed_usd_cents"] == 100000
    assert position["applied_usd_cents"] == position["refunded_usd_cents"] == 0
    assert position["available_usd_cents"] == 0
    collected: list[dict[str, object]] = []
    params = {"limit": "1"}
    for _ in range(9):
        page_result = value(client.get(path, params=params))
        assert page_result["position"] == position
        history = cast(dict[str, object], page_result["history"])
        items = cast(list[dict[str, object]], history["items"])
        assert len(items) == 1
        collected.extend(items)
        page = cast(dict[str, object], history["page"])
        assert page["limit"] == 1
        if page["next_cursor"] is None:
            break
        params["cursor"] = str(page["next_cursor"])
    else:
        pytest.fail("Credit HTTP history cursor did not terminate")
    assert collected == expected and len(collected) == 8
    assert {event["event_kind"] for event in collected} == {
        "RECOGNITION",
        "RECOGNITION_REVERSAL",
        "APPLICATION",
        "APPLICATION_REVERSAL",
        "REFUND",
        "REFUND_VALUE_CORRECTION",
        "REFUND_CORRECTION_REVERSAL",
    }
    balance = 0
    for event in reversed(collected):
        balance += cast(int, event["balance_effect_usd_cents"])
        assert event["available_after_usd_cents"] == balance >= 0
        assert event["currency"] == "USD" and event["actor_id"] == str(human)
    assert snapshot(migrated_database_url, payment) == before


def test_credit_refund_http_large_ledger_keeps_cross_family_event_identity(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from test_refund_migration import refund as insert_refund

    human, prop, customer, payment = source(migrated_database_url, 1000)
    credit = credit_id(recognize(prop, payment, human, 1000))
    with psycopg.connect(migrated_database_url) as connection:
        for index in range(105):
            insert_refund(
                connection,
                human,
                customer,
                credit=credit,
                amount=1,
                overrides={"id": credit} if index == 0 else None,
            )
    client = api(actor(human, prop, "credits.read"))
    path = f"/api/v1/customer-credits/{credit}/ledger"
    before = snapshot(migrated_database_url, payment)
    first = value(client.get(path, params={"limit": "100"}))
    history = cast(dict[str, object], first["history"])
    items = cast(list[dict[str, object]], history["items"])
    assert len(items) == 100
    token = str(cast(dict[str, object], history["page"])["next_cursor"])
    second = value(client.get(path, params={"limit": "100", "cursor": token}))
    following = cast(dict[str, object], second["history"])
    remaining = cast(list[dict[str, object]], following["items"])
    assert len(remaining) == 6
    assert cast(dict[str, object], following["page"])["next_cursor"] is None
    events = items + remaining
    assert len({(e["event_kind"], e["event_id"]) for e in events}) == 106
    assert [e["event_kind"] for e in events if e["event_id"] == str(credit)] == [
        "REFUND",
        "RECOGNITION",
    ]
    assert cast(dict[str, object], first["position"])["available_usd_cents"] == 895
    assert second["position"] == first["position"]
    assert snapshot(migrated_database_url, payment) == before
