"""Environment-backed application settings."""

from typing import Literal
from uuid import UUID

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
    financial_database_url: SecretStr | None = Field(
        default=None,
        validation_alias="APP_FINANCIAL_DATABASE_URL",
    )
    billing_service_actor_id: UUID | None = None
    allowed_browser_origin: str = Field(
        default="https://localhost",
        pattern=r"^https://[^/]+$",
    )
    # Login sub-slice L3c-1 (owner answer (a) to Q-2026-10-21-155): paths only, never a key or a
    # list. Both files are read once at start-up; since login sub-slice L4 the blocklist file is
    # required like the key file.
    totp_key_file: str | None = Field(default=None, validation_alias="APP_TOTP_KEY_FILE")
    password_blocklist_file: str | None = Field(
        default=None,
        validation_alias="APP_PASSWORD_BLOCKLIST_FILE",
    )
