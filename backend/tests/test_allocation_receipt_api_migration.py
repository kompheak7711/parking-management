"""Canonical Allocation/Receipt HTTP workflows over real isolated PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from payment_test_support import seed_payment
from property_rental.allocation_read import AllocationReadService
from property_rental.app import create_app
from property_rental.payment_allocation import PostAllocationsCommand
from property_rental.payment_api import _cursor
from property_rental.settings import Settings
from test_allocation_read_migration import large_history_source
from test_credit_migration import actor
from test_invoice import mutation_headers
from test_invoice_migration import runtime_database_url
from test_payment_allocation_migration import service, source
from test_payment_api_migration import api
from test_payment_migration import fx_payment
from test_reservation_migration import migrated_database_url  # noqa: F401

CAPABILITIES = (
    "payments.read",
    "payments.allocate",
    "payments.allocations.reverse",
    "payments.reverse",
    "receipts.read",
    "receipts.reprint",
)


def snapshot(database_url: str, payment: UUID) -> tuple[object, ...]:
    with psycopg.connect(database_url) as connection:
        value = connection.execute(
            "SELECT to_jsonb(payment),to_jsonb(receipt),"
            "(SELECT count(*) FROM app.payment_allocations WHERE payment_id=payment.id),"
            "(SELECT count(*) FROM app.receipt_reprints WHERE receipt_id=receipt.id),"
            "(SELECT count(*) FROM app.payment_allocation_reversals reversal "
            "JOIN app.payment_allocations allocation "
            "ON allocation.id=reversal.payment_allocation_id "
            "WHERE allocation.payment_id=payment.id) "
            "FROM app.payments payment JOIN app.receipts receipt ON receipt.payment_id=payment.id "
            "WHERE payment.id=%s",
            (payment,),
        ).fetchone()
    assert value is not None
    return value


def test_allocation_receipt_http_real_explicit_post_replay_reversal_and_stable_receipt(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    client = api(actor(human, prop, *CAPABILITIES))
    root = f"/api/v1/payments/{payment}"
    before = snapshot(migrated_database_url, payment)
    original_receipt = client.get(root + "/receipt").json()["data"]["receipt"]
    proposal = client.get(root + "/allocation-proposal")
    assert proposal.status_code == 200
    assert snapshot(migrated_database_url, payment) == before
    headers = {**mutation_headers(), "X-Billing-Actor-ID": str(human)}
    body = {"intent": {"mode": "PROPOSAL", "proposal": proposal.json()["data"]}}
    posted = client.post(root + "/allocations", json=body, headers=headers)
    assert posted.status_code == 201, posted.text
    assert posted.headers["location"] == root + "/allocations"
    replay = client.post(root + "/allocations", json=body, headers=headers)
    assert replay.status_code == 201 and replay.json()["data"] == posted.json()["data"]
    allocations = posted.json()["data"]["allocation_ids"]
    assert len(allocations) == 2
    first = client.get(root + "/allocations", params={"limit": "1"}).json()
    second = client.get(
        root + "/allocations",
        params={"limit": "1", "cursor": first["page"]["next_cursor"]},
    ).json()
    assert {item["id"] for item in first["data"] + second["data"]} == set(allocations)
    assert second["page"]["next_cursor"] is None
    evidence = client.get(root + "/allocations", params={"allocation_id": allocations[0]}).json()[
        "data"
    ]
    assert evidence["allocation"]["proposal_trace"] == proposal.json()["data"]
    reversal_body = {
        "reason": "Correct duplicated Payment",
        "expected_status": "RECEIVED",
    }
    blocked = client.post(root + "/reverse", json=reversal_body, headers=mutation_headers())
    assert blocked.status_code == 503  # Accepted deferred guard retains unknown-outcome semantics.
    assert snapshot(migrated_database_url, payment)[0] == before[0]
    for allocation in allocations:
        command = {"reason": "Correct target"}
        selected_headers = mutation_headers()
        path = f"/api/v1/payment-allocations/{allocation}/reverse"
        original = client.post(path, json=command, headers=selected_headers)
        assert original.status_code == 200, original.text
        assert (
            client.post(path, json=command, headers=selected_headers).json()["data"]
            == original.json()["data"]
        )
        changed = client.post(path, json={"reason": "Changed intent"}, headers=selected_headers)
        assert (
            changed.status_code == 409
            and changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        )
    selected_headers = mutation_headers()
    reversed_payment = client.post(root + "/reverse", json=reversal_body, headers=selected_headers)
    assert reversed_payment.status_code == 200, reversed_payment.text
    assert (
        client.post(root + "/reverse", json=reversal_body, headers=selected_headers).json()["data"]
        == reversed_payment.json()["data"]
    )
    current = client.get(root + "/receipt").json()["data"]
    assert current["receipt"] == original_receipt and current["payment"]["status"] == "REVERSED"
    receipt_path = f"/api/v1/receipts/{original_receipt['id']}"
    events: list[str] = []
    for index in range(3):
        selected_headers = mutation_headers()
        command = {
            "reason": f"Requested copy {index}",
            "delivery_reference": "បង្កាន់ដៃ café",
        }
        copy = client.post(receipt_path + "/reprints", json=command, headers=selected_headers)
        assert copy.status_code == 200, copy.text
        events.append(copy.json()["data"]["reprint"]["id"])
        assert (
            client.post(receipt_path + "/reprints", json=command, headers=selected_headers).json()[
                "data"
            ]
            == copy.json()["data"]
        )
        reused = client.post(
            receipt_path + "/reprints",
            json={**command, "reason": "Changed"},
            headers=selected_headers,
        )
        assert (
            reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        )
    cursor = None
    found: list[str] = []
    for _ in range(3):
        params = {"limit": "1"}
        if cursor is not None:
            params["cursor"] = cursor
        page = client.get(receipt_path, params=params).json()["data"]
        assert page["receipt"] == original_receipt
        found.extend(item["id"] for item in page["reprints"]["items"])
        cursor = page["reprints"]["page"]["next_cursor"]
    assert found == events and cursor is None
    _, _, second_payment, _ = source(migrated_database_url)
    second_receipt = client.get(f"/api/v1/payments/{second_payment}/receipt").json()["data"][
        "receipt"
    ]["id"]
    wrong_history = _cursor({"receipt_id": second_receipt, "after_id": events[0]})
    rejected_cursor = client.get(
        f"/api/v1/receipts/{second_receipt}", params={"cursor": wrong_history}
    )
    assert rejected_cursor.status_code == 400

    after = snapshot(migrated_database_url, payment)
    assert after[1] == before[1] and after[2:] == (2, 3, 2)


@pytest.mark.parametrize(
    "operation",
    [
        "proposal",
        "post",
        "history",
        "reverse_allocation",
        "reverse_payment",
        "payment_receipt",
        "receipt",
        "reprint",
    ],
)
def test_allocation_receipt_http_real_separate_capabilities_and_fresh_disabled_actor(
    migrated_database_url: str,  # noqa: F811
    operation: str,
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    who = actor(human, prop, *CAPABILITIES)
    proposal = AllocationReadService(runtime_database_url()).proposal(prop, payment, actor=who)
    result = service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=who,
    )
    allocation = cast(list[str], result["allocation_ids"])[0]
    before = snapshot(migrated_database_url, payment)
    receipt_id = cast(dict[str, object], before[1])["id"]
    root = f"/api/v1/payments/{payment}"
    routes: dict[str, tuple[str, str, dict[str, object] | None]] = {
        "proposal": ("GET", root + "/allocation-proposal", None),
        "post": (
            "POST",
            root + "/allocations",
            {"intent": {"mode": "PROPOSAL", "proposal": proposal}},
        ),
        "history": ("GET", root + "/allocations", None),
        "reverse_allocation": (
            "POST",
            f"/api/v1/payment-allocations/{allocation}/reverse",
            {"reason": "Not permitted"},
        ),
        "reverse_payment": (
            "POST",
            root + "/reverse",
            {"reason": "Not permitted", "expected_status": "RECEIVED"},
        ),
        "payment_receipt": ("GET", root + "/receipt", None),
        "receipt": ("GET", f"/api/v1/receipts/{receipt_id}", None),
        "reprint": (
            "POST",
            f"/api/v1/receipts/{receipt_id}/reprints",
            {"reason": "Not permitted"},
        ),
    }
    method, path, body = routes[operation]
    for denied in (
        actor(human, prop, "payments.record"),
        actor(human, uuid4(), *CAPABILITIES),
    ):
        assert (
            api(denied).request(method, path, json=body, headers=mutation_headers()).status_code
            == 404
        )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (human,),
        )
    denied = api(who).request(method, path, json=body, headers=mutation_headers())
    assert denied.status_code == 404, denied.text
    assert snapshot(migrated_database_url, payment) == before


def test_allocation_http_real_maximum_detail_proposal_exceeds_payment_cap_and_round_trips_evidence(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, proposal = large_history_source(migrated_database_url)
    client = api(actor(human, prop, "payments.allocate", "payments.read"))
    body = {"intent": {"mode": "PROPOSAL", "proposal": proposal}}
    root = f"/api/v1/payments/{payment}/allocations"
    headers = mutation_headers()
    posted = client.post(root, json=body, headers=headers)
    assert posted.status_code == 201, posted.text
    assert client.post(root, json=body, headers=headers).json()["data"] == posted.json()["data"]
    allocation = posted.json()["data"]["allocation_ids"][0]
    page = client.get(root, params={"allocation_id": allocation, "limit": "100"})
    assert page.status_code == 200
    assert page.json()["data"]["allocation"]["proposal_trace"] == proposal
    assert len(page.json()["data"]["details"]) == 100
    cursor = page.json()["page"]["next_cursor"]
    assert cursor is not None
    assert client.get(root, params={"cursor": cursor}).status_code == 400
    assert (
        client.get(root, params={"allocation_id": str(uuid4()), "cursor": cursor}).status_code
        == 400
    )
    assert (
        client.get(root, params={"allocation_id": allocation, "cursor": cursor}).status_code == 200
    )


def test_allocation_http_real_concurrent_payments_cannot_double_consume_targets(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        second = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(row[0])),
            amount=100_000,
        )
    who = actor(human, prop, "payments.allocate")
    reader = AllocationReadService(runtime_database_url())
    proposals = [(value, reader.proposal(prop, value, actor=who)) for value in (payment, second)]

    client = api(who)

    def post(value: tuple[UUID, dict[str, object]]) -> int:
        identity, proposal = value
        response = client.post(
            f"/api/v1/payments/{identity}/allocations",
            json={"intent": {"mode": "PROPOSAL", "proposal": proposal}},
            headers=mutation_headers(),
        )
        return cast(int, response.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(post, proposals))
    assert statuses[0] == 201 and statuses[1] in {409, 503}
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT sum(amount_usd_cents) FROM app.payment_allocations WHERE payment_id=ANY(%s)",
            ([payment, second],),
        ).fetchone() == (100_000,)


@pytest.mark.parametrize("channel", [False, True])
def test_receipt_http_retains_original_khr_exact_fx_with_independent_receipt_permission(
    migrated_database_url: str,  # noqa: F811
    channel: bool,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(
            connection,
            channel=channel,
            channel_rate=Decimal("4100.123456") if channel else None,
        )
        row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
    human, prop = (UUID(str(value)) for value in row)
    client = api(actor(human, prop, "receipts.read"))
    response = client.get(f"/api/v1/payments/{payment}/receipt")
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["payment"]["received_currency"] == "KHR"
    assert result["payment"]["received_amount_minor"] == 4143
    assert result["payment"]["usd_accounting_value_cents"] == 101
    assert result["fx"]["system_rate_khr_per_usd"] == "4101"
    if channel:
        assert result["fx"]["channel_actual_rate_khr_per_usd"] == "4100.123456"
    assert client.get(f"/api/v1/payments/{payment}/allocations").status_code == 404


def test_receipt_http_runtime_reads_do_not_require_or_borrow_financial_credentials(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    client = TestClient(
        create_app(
            Settings(database_url=SecretStr(runtime_database_url())),
            actor_resolver=lambda _: actor(human, prop, *CAPABILITIES),
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    before = snapshot(migrated_database_url, payment)
    receipt = client.get(f"/api/v1/payments/{payment}/receipt")
    assert receipt.status_code == 200
    receipt_id = receipt.json()["data"]["receipt"]["id"]
    unavailable = client.post(
        f"/api/v1/receipts/{receipt_id}/reprints",
        json={"reason": "No writer configured"},
        headers=mutation_headers(),
    )
    assert unavailable.status_code == 503
    assert snapshot(migrated_database_url, payment) == before
