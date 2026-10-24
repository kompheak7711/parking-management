"""Provider-neutral authenticated actor boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True, slots=True)
class ObjectScope:
    """Exact provider-established object authorization scope."""

    object_type: str
    object_id: str


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """Provider-established capability with its allowed resource scopes."""

    capability: str
    property_ids: frozenset[str] = frozenset()
    object_scopes: frozenset[ObjectScope] = frozenset()


@dataclass(frozen=True, slots=True)
class AuthorizationRequirement:
    """Capability and resource scope declared by a protected operation."""

    capability: str
    property_id: str | None = None
    object_scope: ObjectScope | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Opaque identity and authorization grants established outside the API core."""

    actor_id: str
    capability_grants: frozenset[CapabilityGrant] = frozenset()


ActorResolver = Callable[[Request], AuthenticatedActor | None]


def is_authorized(
    actor: AuthenticatedActor,
    requirement: AuthorizationRequirement,
) -> bool:
    """Allow only an exact capability grant satisfying every required scope."""
    for grant in actor.capability_grants:
        if grant.capability != requirement.capability:
            continue
        if (
            requirement.property_id is not None
            and requirement.property_id not in grant.property_ids
        ):
            continue
        if (
            requirement.object_scope is not None
            and requirement.object_scope not in grant.object_scopes
        ):
            continue
        return True
    return False


def deny_unauthenticated_actor(_: Request) -> None:
    """Deny when no external authentication provider establishes an actor."""
    return None


def remembered_actor(resolver: ActorResolver) -> ActorResolver:
    """The actor of a request resolved once (login sub-slice L5): the route guard and the route
    read the same answer, and the session is looked up once per request."""

    def resolve(request: Request) -> AuthenticatedActor | None:
        remembered: tuple[AuthenticatedActor | None] | None = getattr(
            request.state, "prm_resolved_actor", None
        )
        if remembered is None:
            remembered = (resolver(request),)
            request.state.prm_resolved_actor = remembered
        return remembered[0]

    return resolve
