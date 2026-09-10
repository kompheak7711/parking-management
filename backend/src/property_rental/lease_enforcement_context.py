"""Minimal separately authorized enforcement selection and action context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.lease_enforcement import (
    NONPAYMENT_EVENT,
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    WARNING_CREATE,
    WARNING_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementInvalidError,
    LeaseEnforcementUnavailableError,
    PostgresLeaseEnforcementService,
    _identity,
)

ENFORCEMENT_CAPABILITIES = (
    WARNING_READ,
    WARNING_CREATE,
    NONPAYMENT_READ,
    NONPAYMENT_OPEN,
    NONPAYMENT_EVENT,
)
Purpose = Literal["WARNINGS", "NONPAYMENT"]
ContextKind = Literal[
    "LEASES", "SOURCES", "ACTION_CASES", "EVENT_CONTEXT", "WARNING_CONTEXT", "ALERTS"
]


def grants(actor: AuthenticatedActor, capabilities: tuple[str, ...]) -> list[UUID]:
    ids: set[UUID] = set()
    for grant in actor.capability_grants:
        if grant.capability not in capabilities:
            continue
        for value in grant.property_ids:
            try:
                parsed = UUID(value)
                if parsed.int and str(parsed) == value:
                    ids.add(parsed)
            except (ValueError, TypeError, AttributeError):
                continue
    return sorted(ids)


def capabilities(actor: AuthenticatedActor, prop: UUID) -> dict[str, bool]:
    return {
        cap: is_authorized(actor, AuthorizationRequirement(cap, str(prop)))
        for cap in ENFORCEMENT_CAPABILITIES
    }


@dataclass(frozen=True, slots=True)
class EnforcementPage:
    limit: int = 50
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise LeaseEnforcementInvalidError("Enforcement page limit is invalid")
        if self.after_id is not None:
            _identity(self.after_id, "cursor")


@dataclass(frozen=True, slots=True)
class EnforcementScope:
    property_id: UUID
    lease_id: UUID


@dataclass(frozen=True, slots=True)
class PostgresEnforcementContext:
    database_url: str | None

    def _service(self) -> PostgresLeaseEnforcementService:
        if not self.database_url:
            raise LeaseEnforcementUnavailableError("Enforcement context is unavailable")
        return PostgresLeaseEnforcementService(self.database_url)

    @staticmethod
    def _actor(actor: AuthenticatedActor) -> UUID:
        try:
            value = UUID(actor.actor_id)
            _identity(value, "actor_id")
            return value
        except (ValueError, TypeError, AttributeError) as exc:
            raise LeaseEnforcementAuthorizationError("Enforcement actor is invalid") from exc

    def resolve(
        self,
        kind: Literal["LEASE", "CASE"],
        identity: UUID,
        capability: str,
        *,
        actor: AuthenticatedActor,
    ) -> EnforcementScope:
        _identity(identity, "resource_id")
        if kind not in {"LEASE", "CASE"} or capability not in ENFORCEMENT_CAPABILITIES:
            raise LeaseEnforcementInvalidError("Enforcement resolution is invalid")
        result = self._service()._query(
            "SELECT app.lease_enforcement_resolve(%s,%s,%s,%s)",
            (self._actor(actor), grants(actor, (capability,)), kind, identity),
            write=False,
        )
        try:
            prop, lease = UUID(str(result["property_id"])), UUID(str(result["lease_id"]))
            _identity(lease, "lease_id")
            PostgresLeaseEnforcementService._authorize(actor, prop, capability, hide=True)
            if kind == "LEASE" and lease != identity:
                raise ValueError
            return EnforcementScope(prop, lease)
        except (KeyError, ValueError, TypeError) as exc:
            raise LeaseEnforcementUnavailableError("Enforcement resolution is unavailable") from exc

    def workspaces(self, page: EnforcementPage, *, actor: AuthenticatedActor) -> dict[str, object]:
        checked = EnforcementPage(page.limit, page.after_id)
        # Fresh actor and explicit Property selection share one read-only snapshot.
        result = self._service()._query(
            "SELECT app.lease_enforcement_workspaces(%s,%s,%s,%s)",
            (
                self._actor(actor),
                grants(actor, ENFORCEMENT_CAPABILITIES),
                checked.limit,
                checked.after_id,
            ),
            write=False,
        )
        rows = cast(list[dict[str, object]], result["items"])
        return {
            "items": [
                {**row, "capabilities": capabilities(actor, UUID(str(row["property_id"])))}
                for row in rows[: checked.limit]
            ],
            "next_cursor": rows[checked.limit - 1]["property_id"]
            if len(rows) > checked.limit
            else None,
        }

    def read(
        self,
        property_id: UUID,
        kind: ContextKind,
        *,
        actor: AuthenticatedActor,
        lease_id: UUID | None = None,
        case_id: UUID | None = None,
        page: EnforcementPage | None = None,
        purpose: Purpose | None = None,
    ) -> dict[str, object]:
        selected = page if page is not None else EnforcementPage()
        checked = EnforcementPage(selected.limit, selected.after_id)
        needed: tuple[str, ...] | None = {
            "SOURCES": (NONPAYMENT_OPEN,),
            "ACTION_CASES": (NONPAYMENT_EVENT,),
            "EVENT_CONTEXT": (NONPAYMENT_EVENT,),
            "WARNING_CONTEXT": (WARNING_CREATE,),
            "ALERTS": (NONPAYMENT_READ,),
        }.get(kind)
        if kind == "LEASES":
            if purpose not in {"WARNINGS", "NONPAYMENT"}:
                raise LeaseEnforcementInvalidError("Enforcement selection purpose is invalid")
            needed = (
                (WARNING_READ, WARNING_CREATE)
                if purpose == "WARNINGS"
                else (NONPAYMENT_READ, NONPAYMENT_OPEN, NONPAYMENT_EVENT)
            )
        elif purpose is not None:
            raise LeaseEnforcementInvalidError("Enforcement purpose is not applicable")
        if needed is None:
            raise LeaseEnforcementInvalidError("Enforcement context kind is invalid")
        _identity(property_id, "property_id")
        if not any(
            is_authorized(actor, AuthorizationRequirement(cap, str(property_id))) for cap in needed
        ):
            raise LeaseEnforcementAuthorizationError("Enforcement context is not authorized")
        if lease_id is not None:
            _identity(lease_id, "lease_id")
        if case_id is not None:
            _identity(case_id, "case_id")
        return self._service()._query(
            "SELECT app.lease_enforcement_context(%s,%s,%s,%s,%s,%s,%s)",
            (
                self._actor(actor),
                property_id,
                kind,
                lease_id,
                case_id,
                checked.limit,
                checked.after_id,
            ),
            write=False,
        )
