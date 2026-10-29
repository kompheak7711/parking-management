"""Tests for the single Property configuration domain and service."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

import property_rental.property_setup_cli as property_setup_cli
from property_rental.business_time import PROPERTY_TIMEZONE_NAME
from property_rental.property import (
    PropertyAlreadyConfiguredError,
    PropertyConfiguration,
    PropertyConfigurationService,
    PropertyNotConfiguredError,
    configure_postgres_property,
)
from property_rental.settings import Settings


@dataclass(slots=True)
class InMemoryPropertyConfigurationRepository:
    """Minimal repository double for service-boundary tests."""

    configuration: PropertyConfiguration | None = None
    add_calls: int = 0

    def get(self) -> PropertyConfiguration | None:
        return self.configuration

    def add(self, configuration: PropertyConfiguration) -> None:
        self.add_calls += 1
        self.configuration = configuration


def test_property_configuration_uses_authoritative_timezone() -> None:
    property_id = uuid4()

    configuration = PropertyConfiguration(property_id=property_id, name="Riverside")

    assert configuration.property_id == property_id
    assert configuration.timezone_name == "Asia/Phnom_Penh"
    assert configuration.timezone_name == PROPERTY_TIMEZONE_NAME


def test_property_configuration_rejects_nil_identity() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        PropertyConfiguration(property_id=UUID(int=0), name="Riverside")


def test_property_configuration_rejects_non_authoritative_timezone() -> None:
    with pytest.raises(ValueError, match="Asia/Phnom_Penh"):
        PropertyConfiguration(property_id=uuid4(), name="Riverside", timezone_name="UTC")


def test_property_configuration_rejects_blank_source_fields() -> None:
    with pytest.raises(ValueError, match="name"):
        PropertyConfiguration(property_id=uuid4(), name=" ")
    with pytest.raises(ValueError, match="address_text"):
        PropertyConfiguration(property_id=uuid4(), name="Riverside", address_text=" ")


def test_service_configures_exactly_one_property() -> None:
    repository = InMemoryPropertyConfigurationRepository()
    service = PropertyConfigurationService(repository)
    property_id = uuid4()

    configuration = service.configure(property_id, name="Riverside")

    assert configuration == PropertyConfiguration(property_id=property_id, name="Riverside")
    assert repository.configuration == configuration
    assert repository.add_calls == 1


def test_service_rejects_a_second_property_without_persisting_it() -> None:
    existing = PropertyConfiguration(property_id=uuid4(), name="Riverside")
    repository = InMemoryPropertyConfigurationRepository(configuration=existing)
    service = PropertyConfigurationService(repository)

    with pytest.raises(PropertyAlreadyConfiguredError, match="already"):
        service.configure(uuid4(), name="Second Property")

    assert repository.configuration == existing
    assert repository.add_calls == 0


def test_service_requires_an_existing_configuration() -> None:
    service = PropertyConfigurationService(InMemoryPropertyConfigurationRepository())

    with pytest.raises(PropertyNotConfiguredError, match="does not have"):
        service.require_configuration()


def test_service_returns_the_existing_configuration() -> None:
    existing = PropertyConfiguration(property_id=uuid4(), name="Riverside")
    service = PropertyConfigurationService(
        InMemoryPropertyConfigurationRepository(configuration=existing)
    )

    assert service.require_configuration() == existing


def test_postgres_setup_entrypoint_uses_the_protected_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    actor_id = uuid4()
    observed: list[tuple[str, UUID]] = []

    class FakePostgresRepository(InMemoryPropertyConfigurationRepository):
        def __init__(self, database_url: str, configured_actor_id: UUID) -> None:
            super().__init__()
            observed.append((database_url, configured_actor_id))

    monkeypatch.setattr(
        "property_rental.property.PostgresPropertyConfigurationRepository",
        FakePostgresRepository,
    )

    configured = configure_postgres_property(
        "postgresql://runtime",
        property_id,
        name="Riverside",
        actor_id=actor_id,
    )

    assert configured == PropertyConfiguration(property_id, name="Riverside")
    assert observed == [("postgresql://runtime", actor_id)]


def test_property_setup_command_uses_runtime_database_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    actor_id = uuid4()
    observed: list[tuple[str, UUID, str, str | None, UUID]] = []

    def configure(
        database_url: str,
        configured_id: UUID,
        *,
        name: str,
        address_text: str | None,
        actor_id: UUID,
    ) -> PropertyConfiguration:
        observed.append((database_url, configured_id, name, address_text, actor_id))
        return PropertyConfiguration(configured_id, name=name)

    monkeypatch.setattr(property_setup_cli, "configure_postgres_property", configure)

    result = property_setup_cli.main(
        [
            "--property-id",
            str(property_id),
            "--name",
            "Riverside",
            "--address",
            "Phnom Penh",
            "--actor-id",
            str(actor_id),
        ],
        settings=Settings(database_url="postgresql://runtime"),
    )

    assert result == 0
    assert observed == [("postgresql://runtime", property_id, "Riverside", "Phnom Penh", actor_id)]


def test_property_setup_command_finds_the_owner_and_makes_the_identifier(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = uuid4()
    observed: list[tuple[UUID, UUID]] = []
    monkeypatch.setattr(property_setup_cli, "owner_actor_id", lambda database_url: owner)

    def configure(
        database_url: str,
        configured_id: UUID,
        *,
        name: str,
        address_text: str | None,
        actor_id: UUID,
    ) -> PropertyConfiguration:
        observed.append((configured_id, actor_id))
        return PropertyConfiguration(configured_id, name=name)

    monkeypatch.setattr(property_setup_cli, "configure_postgres_property", configure)

    result = property_setup_cli.main(
        ["--name", "CHETANA Parking"], settings=Settings(database_url="postgresql://runtime")
    )

    assert result == 0
    assert len(observed) == 1 and observed[0][1] == owner
    assert "CHETANA Parking is set up" in capsys.readouterr().out


def test_property_setup_command_needs_the_owner_and_runs_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(property_setup_cli, "owner_actor_id", lambda database_url: None)
    with pytest.raises(SystemExit):
        property_setup_cli.main(["--name", "X"], settings=Settings(database_url="postgresql://r"))

    def already(*_: object, **__: object) -> PropertyConfiguration:
        raise PropertyAlreadyConfiguredError("already")

    monkeypatch.setattr(property_setup_cli, "configure_postgres_property", already)
    result = property_setup_cli.main(
        ["--name", "X", "--actor-id", str(uuid4())],
        settings=Settings(database_url="postgresql://r"),
    )
    assert result == 0
    assert "already set up" in capsys.readouterr().out
