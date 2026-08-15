"""Provider-neutral authenticated actor boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Opaque stable identity established outside the API core."""

    actor_id: str


ActorResolver = Callable[[Request], AuthenticatedActor | None]


def deny_unauthenticated_actor(_: Request) -> None:
    """Deny when no external authentication provider establishes an actor."""
    return None
