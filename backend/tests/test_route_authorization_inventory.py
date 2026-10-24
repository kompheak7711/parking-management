"""Login sub-slice L5: every route outside sign-in and health needs a signed-in user first.

SEC-002, SEC-003, SEC-016, SEC-019, SEC-023, API-008, TEST-084, TEST-085, TEST-109 (DL-081;
Q-2026-10-24-186). The test walks every operation of the application's OpenAPI document. The
operations that run without a session are listed here, so a new open route fails the test until
it is listed on purpose, and the app serves no route outside that document (no generated
documentation pages). Every other operation answers 401 without a session, whatever JSON body it
gets; every other change answers 403 without the configured Origin or the CSRF pair, before its
body is validated (FastAPI parses the JSON first, so a body that is not JSON answers 400); and no
other read gives anything to a signed-in user who holds no capability.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from test_initial_owner_bootstrap_cli import _collect_runtime_http_operations

# The health routes and the sign-in routes: they run before a session exists, or check the
# session cookie and the pre-authentication cookie themselves (API-096, API-097, API-098).
OPEN_OPERATIONS = frozenset(
    {
        ("get", "/api/v1/health/live"),
        ("get", "/api/v1/health/ready"),
        ("get", "/api/v1/identity/me"),
        ("post", "/api/v1/auth/login"),
        ("post", "/api/v1/auth/password-change"),
        ("post", "/api/v1/auth/mfa/challenge"),
        ("post", "/api/v1/auth/mfa/enrollment"),
        ("post", "/api/v1/auth/mfa/enrollment/confirm"),
        ("get", "/api/v1/auth/session"),
        ("post", "/api/v1/auth/logout"),
        ("post", "/api/v1/auth/reauthenticate"),
        ("post", "/api/v1/auth/recovery-codes"),
        ("post", "/api/v1/auth/recovery-codes/regenerate"),
    }
)
# Reads that answer what the signed-in user may do; with no capability they allow nothing.
CAPABILITY_SUMMARIES = {
    "/api/v1/properties/{property_id}/billing-capabilities": {"billing_capabilities": []},
    "/api/v1/properties/{property_id}/configuration-capabilities": {
        "read": False,
        "manage_service_rates": False,
        "manage_utility_rates": False,
        "manage_exchange_rates": False,
    },
}
# The customer ledger reads refuse any GET body (400) before anything else runs, so with a body
# they answer 400 to everyone, signed in or not; they reveal nothing.
BODY_REFUSING_READS = frozenset(
    {
        ("get", "/api/v1/customer-ledger/customers"),
        ("get", "/api/v1/customers/{customer_id}/account-ledger"),
    }
)
# A route that answers 409 to every call that passes its checks (no Occupancy end command yet).
ALWAYS_REFUSED = frozenset({("post", "/api/v1/occupancies/{occupancy_id}/end")})
ORIGIN = "https://localhost"
CSRF = "inventory-csrf-token"
NOBODY = AuthenticatedActor(actor_id=str(uuid.uuid4()))


def operations() -> list[tuple[str, str]]:
    document = create_app(actor_resolver=lambda _: None).openapi()
    return sorted(
        (method, path)
        for path, methods in document["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    )


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def guarded() -> list[tuple[str, str]]:
    return [operation for operation in operations() if operation not in OPEN_OPERATIONS]


def test_the_listed_open_operations_exist_and_the_app_serves_nothing_else() -> None:
    """Every listed open operation exists and the guarded ones are the rest (more than 150); the
    app serves no route outside its OpenAPI document (review round 1: the generated
    documentation pages answered without a session)."""
    assert OPEN_OPERATIONS <= set(operations())
    assert len(guarded()) > 150
    served = _collect_runtime_http_operations(create_app(actor_resolver=lambda _: None).routes)
    assert {
        (method, path) for path, methods in served.items() for method in methods - {"head"}
    } == set(operations())
    client = TestClient(create_app(actor_resolver=lambda _: None))
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("body", [None, {}, {"unexpected": True}])
def test_every_guarded_operation_answers_401_without_a_session(body: object) -> None:
    client = TestClient(create_app(actor_resolver=lambda _: None))
    answers = {
        (method, path): client.request(method.upper(), concrete(path), json=body).status_code
        for method, path in guarded()
    }
    expected = {
        operation: 400 if body is not None and operation in BODY_REFUSING_READS else 401
        for operation in answers
    }
    assert {op: code for op, code in answers.items() if code != expected[op]} == {}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://elsewhere.example", "X-CSRF-Token": CSRF},
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "X-CSRF-Token": "another-token"},
    ],
    ids=["nothing", "other-origin", "no-csrf-header", "csrf-mismatch"],
)
def test_every_guarded_change_needs_the_origin_and_the_csrf_pair_first(
    headers: dict[str, str],
) -> None:
    client = TestClient(create_app(actor_resolver=lambda _: NOBODY))
    cookies = {"Cookie": f"__Host-prm_csrf={CSRF}"} if "X-CSRF-Token" in headers else {}
    answers = {
        (method, path): client.request(
            method.upper(), concrete(path), json={}, headers={**headers, **cookies}
        ).status_code
        for method, path in guarded()
        if method != "get"
    }
    assert answers
    assert {operation: code for operation, code in answers.items() if code != 403} == {}


def test_no_guarded_read_gives_anything_to_a_user_without_capabilities() -> None:
    """Without a database a read that checks its capability there fails closed (503); a read
    that hides what exists answers 404; every other read answers 403. The capability summaries
    answer that nothing is allowed."""
    client = TestClient(create_app(actor_resolver=lambda _: NOBODY))
    answers = {path: client.get(concrete(path)) for method, path in guarded() if method == "get"}
    for path, expected in CAPABILITY_SUMMARIES.items():
        response = answers.pop(path)
        assert response.status_code == 200
        data = response.json()["data"]
        data.pop("property_id", None)
        assert data == expected
    assert {
        path: response.status_code
        for path, response in answers.items()
        if response.status_code not in {400, 403, 404, 422, 503}
    } == {}


@pytest.mark.parametrize(
    "path",
    [
        "/properties/{property_id}",
        "/properties/{property_id}/units",
        "/units/{unit_id}",
        "/units/{unit_id}/timeline",
        "/properties/{property_id}/configuration",
    ],
)
def test_the_property_and_unit_reads_answer_403_without_their_capability(path: str) -> None:
    """Owner answer (a) to Q-2026-10-21-160: the four reads that needed only a session now need
    `property.read` or `units.read`, checked before anything is read."""
    client = TestClient(create_app(actor_resolver=lambda _: NOBODY))
    assert client.get(concrete(path)).status_code == 403


def test_no_guarded_change_succeeds_for_a_user_without_capabilities() -> None:
    """With the configured Origin and the CSRF pair, a change sent by a signed-in user who holds
    no capability never succeeds and never fails open: it answers a refusal, a request error or
    503 (a check in the database fails closed without one)."""
    client = TestClient(create_app(actor_resolver=lambda _: NOBODY))
    headers = {"Origin": ORIGIN, "X-CSRF-Token": CSRF, "Cookie": f"__Host-prm_csrf={CSRF}"}
    answers = {
        (method, path): client.request(
            method.upper(), concrete(path), json={}, headers=headers
        ).status_code
        for method, path in guarded()
        if method != "get"
    }
    assert answers
    assert {
        operation: code
        for operation, code in answers.items()
        if code not in {400, 403, 404, 412, 422, 428, 503}
        and not (code == 409 and operation in ALWAYS_REFUSED)
    } == {}
