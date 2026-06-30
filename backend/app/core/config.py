"""Application settings.

All secrets (database credentials, encryption key, JWT signing key, SMTP and
TURN credentials) are read exclusively from environment variables. No secret
value is ever hard-coded here (Requirement 21.3, 13.6).

Use ``get_settings()`` to obtain a cached ``Settings`` instance.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables.

    Secret-bearing fields intentionally have no default value baked into the
    source. They are populated from the process environment (or a local, never
    committed ``.env`` file) at runtime. Fields are typed ``Optional`` so the
    application can import cleanly in environments where a particular secret is
    not required (e.g. running unit tests that do not touch SMTP), while still
    forbidding hard-coded secret literals.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Care-Connect-EMR"
    environment: str = Field(default="development")
    api_v1_prefix: str = "/api/v1"

    cors_allow_origins: str = Field(default="")

    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")

    emr_encryption_key: Optional[str] = Field(
        default=None, alias="EMR_ENCRYPTION_KEY"
    )

    jwt_secret: Optional[str] = Field(default=None, alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expires_hours: int = Field(default=24, alias="JWT_EXPIRES_HOURS")

    bcrypt_rounds: int = Field(default=12, alias="BCRYPT_ROUNDS")

    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: Optional[str] = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from_email: Optional[str] = Field(default=None, alias="SMTP_FROM_EMAIL")

    turn_url: Optional[str] = Field(default=None, alias="TURN_URL")
    turn_username: Optional[str] = Field(default=None, alias="TURN_USERNAME")
    turn_credential: Optional[str] = Field(default=None, alias="TURN_CREDENTIAL")
    stun_url: str = Field(default="stun:stun.l.google.com:19302", alias="STUN_URL")

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS origin list into a clean list."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance loaded from the environment."""
    return Settings()
