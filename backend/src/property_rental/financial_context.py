"""Bind a browser's selected Property to the existing authorized financial scope."""

import re
from uuid import UUID

from fastapi import HTTPException, Request

PROPERTY_HEADER = "X-Financial-Property-ID"
PROPERTY_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def bind_financial_property(request: Request, property_id: UUID) -> None:
    """Call after authoritative authorization and before any mutation dispatch."""
    values = request.headers.getlist(PROPERTY_HEADER)
    if len(values) > 1:
        raise HTTPException(400)
    if values:
        value = values[0]
        if PROPERTY_PATTERN.fullmatch(value) is None:
            raise HTTPException(400)
        expected = UUID(value)
        if expected.int == 0:
            raise HTTPException(400)
        if expected != property_id:
            raise HTTPException(404)
    request.state.financial_property_id = property_id


def financial_metadata(request: Request) -> dict[str, str]:
    """Only successful authorized scope is exposed, never the expectation header."""
    property_id = request.state.financial_property_id
    if not isinstance(property_id, UUID) or property_id.int == 0:
        raise HTTPException(503)
    return {"request_id": request.state.request_id, "property_id": str(property_id)}
