"""Identity boundary for objects assigned to the single Property."""

from dataclasses import dataclass
from typing import Protocol


class PropertyAssigned(Protocol):
    """Object exposing its authoritative Property identity."""

    @property
    def property_id(self) -> str:
        """Return the Property ID assigned to this object."""
        ...


@dataclass(frozen=True, slots=True)
class SinglePropertyIdentityScope:
    """Identity scope for the one Property managed by this application."""

    property_id: str

    def require_in_scope(self, assigned_object: PropertyAssigned) -> None:
        """Reject an object unless it is assigned to this Property."""
        if assigned_object.property_id != self.property_id:
            raise ValueError("object is assigned to a different Property ID")
