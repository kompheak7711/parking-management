"""Application-level safe error contract tests (API-013, API-014, TEST-088)."""

import asyncio
from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Path

from property_rental.app import create_app
from property_rental.settings import Settings


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    content: str | None = None,
) -> httpx.Response:
    """Issue one in-process request while retaining handled 500 responses."""

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Request-ID": "error-contract-request"}
            if content is not None:
                headers["Content-Type"] = "application/json"
            return await client.request(
                method,
                path,
                headers=headers,
                content=content,
            )

    return asyncio.run(send())


def assert_error_envelope(
    response: httpx.Response,
    *,
    status_code: int,
    code: str,
    message: str,
    fields: list[str] | None = None,
) -> None:
    assert response.status_code == status_code
    assert response.headers["x-request-id"] == "error-contract-request"
    assert response.json() == {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or [],
            "rule_ids": [],
            "current_version": None,
        },
        "meta": {"request_id": "error-contract-request"},
    }


def test_route_not_found_uses_safe_canonical_error_envelope() -> None:
    response = request(create_app(Settings()), "GET", "/api/v1/private-record/known-id")

    assert_error_envelope(
        response,
        status_code=404,
        code="NOT_FOUND",
        message="The requested resource was not found.",
    )
    assert "private-record" not in response.text
    assert "known-id" not in response.text


def test_http_exception_uses_status_mapping_without_exception_detail() -> None:
    app = create_app(Settings())

    @app.get("/_test/conflict")
    def conflict() -> None:
        raise HTTPException(
            status_code=409,
            detail="duplicate key value violates unique constraint secret_tenant_key",
        )

    response = request(app, "GET", "/_test/conflict")

    assert_error_envelope(
        response,
        status_code=409,
        code="CONFLICT",
        message="The request conflicts with the current resource state.",
    )
    assert "duplicate key" not in response.text
    assert "secret_tenant_key" not in response.text


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    [
        (400, "BAD_REQUEST", "The request could not be processed."),
        (401, "UNAUTHORIZED", "Authentication is required."),
        (403, "FORBIDDEN", "The request is not permitted."),
        (404, "NOT_FOUND", "The requested resource was not found."),
        (409, "CONFLICT", "The request conflicts with the current resource state."),
        (412, "PRECONDITION_FAILED", "A required request precondition was not met."),
        (422, "VALIDATION_ERROR", "The request did not match the required schema."),
        (429, "RATE_LIMITED", "Too many requests."),
        (500, "INTERNAL_ERROR", "An unexpected internal error occurred."),
        (503, "SERVICE_UNAVAILABLE", "A required service is temporarily unavailable."),
    ],
)
def test_canonical_http_statuses_have_exact_safe_contracts(
    status_code: int,
    code: str,
    message: str,
) -> None:
    app = create_app(Settings())

    @app.get("/_test/http-error")
    def http_error() -> None:
        raise HTTPException(status_code=status_code, detail="unsafe exception detail")

    response = request(app, "GET", "/_test/http-error")

    assert_error_envelope(
        response,
        status_code=status_code,
        code=code,
        message=message,
    )
    assert "unsafe exception detail" not in response.text


def test_schema_validation_returns_only_safe_field_locations() -> None:
    app = create_app(Settings())

    @app.get("/_test/items/{item_id}")
    def validated_item(item_id: Annotated[int, Path(ge=1)]) -> dict[str, int]:
        return {"item_id": item_id}

    response = request(app, "GET", "/_test/items/not-an-integer")

    assert_error_envelope(
        response,
        status_code=422,
        code="VALIDATION_ERROR",
        message="The request did not match the required schema.",
        fields=["path.item_id"],
    )
    assert "not-an-integer" not in response.text
    assert "integer_parsing" not in response.text


def test_malformed_json_returns_safe_bad_request_envelope() -> None:
    app = create_app(Settings())

    @app.post("/_test/request-body")
    def request_body(payload: dict[str, str]) -> dict[str, str]:
        return payload

    rejected_content = '{"private_note":"known-secret"'
    response = request(
        app,
        "POST",
        "/_test/request-body",
        content=rejected_content,
    )

    assert_error_envelope(
        response,
        status_code=400,
        code="BAD_REQUEST",
        message="The request could not be processed.",
    )
    assert "json_invalid" not in response.text
    assert "JSON decode error" not in response.text
    assert "known-secret" not in response.text


@pytest.mark.parametrize(
    "diagnostic",
    [
        "Traceback: SELECT password FROM customer_credentials",
        "database authentication secret was exposed in an internal diagnostic",
        "/srv/property-rental/.env: SECRET_KEY=credential",
        "record customer-123 exists but access was denied",
    ],
)
def test_unexpected_exception_returns_redacted_internal_error(diagnostic: str) -> None:
    app = create_app(Settings())

    @app.get("/_test/internal-error")
    def internal_error() -> None:
        raise RuntimeError(diagnostic)

    response = request(app, "GET", "/_test/internal-error")

    assert_error_envelope(
        response,
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected internal error occurred.",
    )
    assert diagnostic not in response.text
