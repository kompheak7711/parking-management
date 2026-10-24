"""Shared browser-mutation protections for cookie-authenticated APIs."""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from property_rental.identity import ActorResolver
from property_rental.settings import Settings

CSRF_COOKIE_NAME = "__Host-prm_csrf"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_browser_mutation(request: Request, settings: Settings) -> None:
    """Require the configured Origin and a double-submit CSRF token."""
    if request.headers.get("origin") != settings.allowed_browser_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        cookie_token is None
        or header_token is None
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def signed_in_browser_request(
    resolver: ActorResolver, settings: Settings
) -> Callable[[Request], None]:
    """The first check of every route outside sign-in and health (login sub-slice L5, SEC-002,
    SEC-016): a request without a signed-in user answers 401, and a change without the
    configured Origin and the CSRF pair answers 403, before the body is validated (FastAPI parses
    the JSON first, so a body that is not JSON answers 400). The route's own checks still run
    after it."""

    def require(request: Request) -> None:
        if resolver(request) is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if request.method not in SAFE_METHODS:
            require_browser_mutation(request, settings)

    return require
