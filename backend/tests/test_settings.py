"""Settings boundary tests (DEPLOY-018, DEPLOY-020, SEC-049)."""

import pytest

from property_rental.settings import Settings


def test_settings_load_non_secret_build_identity_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_BUILD_VERSION", "git-abc123")

    settings = Settings()

    assert settings.build_version == "git-abc123"


def test_settings_keep_runtime_database_url_separate_from_migration_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://migrator:secret@db/prm")
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)

    assert Settings().database_url is None

    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://runtime:secret@db/prm")
    settings = Settings()
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().startswith("postgresql://runtime:")
