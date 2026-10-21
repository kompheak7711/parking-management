"""Domain and service boundary for the single Property configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import psycopg

from property_rental.business_time import PROPERTY_TIMEZONE_NAME

NIL_UUID = UUID(int=0)


class PropertyAlreadyConfiguredError(ValueError):
    """Raised when an attempt is made to configure a second Property."""


class PropertyNotConfiguredError(LookupError):
    """Raised when the deployed application's Property has not been configured."""


@dataclass(frozen=True, slots=True)
class PropertyConfiguration:
    """The immutable identity and authoritative timezone of the single Property."""

    property_id: UUID
    name: str
    address_text: str | None = None
    timezone_name: str = PROPERTY_TIMEZONE_NAME

    def __post_init__(self) -> None:
        """Enforce the Property identity and timezone invariants."""
        if self.property_id == NIL_UUID:
            raise ValueError("property_id must not be the nil UUID")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if self.address_text is not None and not self.address_text.strip():
            raise ValueError("address_text must be null or nonblank")
        if self.timezone_name != PROPERTY_TIMEZONE_NAME:
            raise ValueError(f"timezone_name must be {PROPERTY_TIMEZONE_NAME}")


class PropertyConfigurationRepository(Protocol):
    """Persistence operations required by the Property configuration service."""

    def get(self) -> PropertyConfiguration | None:
        """Return the single Property configuration, if it exists."""
        ...

    def add(self, configuration: PropertyConfiguration) -> None:
        """Persist the initial Property configuration."""
        ...


@dataclass(frozen=True, slots=True)
class PostgresPropertyConfigurationRepository:
    """Initialize and read the single Property through its protected DB function."""

    database_url: str
    actor_id: UUID

    def get(self) -> PropertyConfiguration | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT property_id, name, address_text, timezone_name
                FROM app.property_configuration
                """
            ).fetchone()
        if row is None:
            return None
        return PropertyConfiguration(
            property_id=UUID(str(row[0])),
            name=str(row[1]),
            address_text=None if row[2] is None else str(row[2]),
            timezone_name=str(row[3]),
        )

    def add(self, configuration: PropertyConfiguration) -> None:
        expected = (
            configuration.property_id,
            configuration.name.strip(),
            configuration.address_text,
            configuration.timezone_name,
        )
        with psycopg.connect(self.database_url) as connection:
            try:
                row = connection.execute(
                    """
                    SELECT property_id, name, address_text, timezone_name
                    FROM app.initialize_property(%s, %s, %s, %s)
                    """,
                    (
                        configuration.property_id,
                        configuration.name,
                        configuration.address_text or "",
                        self.actor_id,
                    ),
                ).fetchone()
            except psycopg.errors.UniqueViolation as error:
                raise PropertyAlreadyConfiguredError(
                    "this deployment already has a Property configuration"
                ) from error
            # Checked before the commit (review round 1 of sub-slice L1c), so an invalid
            # result rolls back the new Property and its default bundles together.
            if row != expected:
                raise RuntimeError("Property initialization returned an invalid result")
            # The default Owner, Manager and Staff bundles, in the same transaction as the new
            # Property (login sub-slice L1c, DL-081).
            connection.execute(
                "SELECT owner_bundle_id FROM app.seed_default_role_bundles(%s)",
                (configuration.property_id,),
            )


@dataclass(frozen=True, slots=True)
class PropertyConfigurationService:
    """Configure and retrieve the one Property managed by this deployment."""

    repository: PropertyConfigurationRepository

    def configure(
        self,
        property_id: UUID,
        *,
        name: str,
        address_text: str | None = None,
    ) -> PropertyConfiguration:
        """Persist the initial configuration, rejecting every later creation."""
        if self.repository.get() is not None:
            raise PropertyAlreadyConfiguredError(
                "this deployment already has a Property configuration"
            )

        configuration = PropertyConfiguration(
            property_id=property_id,
            name=name.strip(),
            address_text=None if address_text is None else address_text.strip(),
        )
        self.repository.add(configuration)
        return configuration

    def require_configuration(self) -> PropertyConfiguration:
        """Return the configured Property or fail if setup is incomplete."""
        configuration = self.repository.get()
        if configuration is None:
            raise PropertyNotConfiguredError(
                "this deployment does not have a Property configuration"
            )
        return configuration


def configure_postgres_property(
    database_url: str,
    property_id: UUID,
    *,
    name: str,
    actor_id: UUID,
    address_text: str | None = None,
) -> PropertyConfiguration:
    """Application-controlled one-time setup entrypoint for a fresh deployment."""
    return PropertyConfigurationService(
        PostgresPropertyConfigurationRepository(database_url, actor_id)
    ).configure(property_id, name=name, address_text=address_text)
