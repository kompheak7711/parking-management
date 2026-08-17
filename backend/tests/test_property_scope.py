"""Tests for the single-Property identity scope boundary."""

from dataclasses import dataclass

import pytest

from property_rental.property_scope import SinglePropertyIdentityScope


@dataclass(frozen=True, slots=True)
class AssignedObject:
    """Minimal object carrying its authoritative Property assignment."""

    property_id: str


def test_single_property_scope_accepts_object_assigned_to_its_property() -> None:
    scope = SinglePropertyIdentityScope(property_id="property-primary")

    scope.require_in_scope(AssignedObject(property_id="property-primary"))


def test_single_property_scope_rejects_object_assigned_to_different_property() -> None:
    scope = SinglePropertyIdentityScope(property_id="property-primary")

    with pytest.raises(ValueError, match="different Property ID"):
        scope.require_in_scope(AssignedObject(property_id="property-other"))
