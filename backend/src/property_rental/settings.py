"""Environment-backed application settings."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret settings required by the foundation application."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "property-rental-backend"
    build_version: str = Field(default="development", min_length=1, max_length=128)
    database_url: SecretStr | None = Field(default=None, validation_alias="APP_DATABASE_URL")
