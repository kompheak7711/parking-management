"""Settings boundary tests (DEPLOY-018, DEPLOY-020, SEC-049)."""

import pytest

from property_rental.settings import Settings


def test_settings_load_non_secret_build_identity_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_BUILD_VERSION", "git-abc123")

    settings = Settings()

    assert settings.build_version == "git-abc123"
