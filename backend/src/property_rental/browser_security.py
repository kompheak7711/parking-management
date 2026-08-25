"""Shared browser-mutation protections for cookie-authenticated APIs."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from property_rental.settings import Settings

CSRF_COOKIE_NAME = "__Host-prm_csrf"


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
