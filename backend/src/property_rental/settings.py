"""Environment-backed application settings."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret settings required by the foundation application."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    service_name: str = "property-rental-backend"
    build_version: str = Field(default="development", min_length=1, max_length=128)
    environment: str = Field(default="development", min_length=1, max_length=64)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr | None = Field(default=None, validation_alias="APP_DATABASE_URL")
    allowed_browser_origin: str = Field(
        default="https://localhost",
        pattern=r"^https://[^/]+$",
    )
