"""Application configuration.

All configuration is loaded from environment variables (and, in local development,
the repository-root `.env` file which is never committed). Secrets are held as
`SecretStr` so they cannot be accidentally logged or serialised.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "apps" / "api" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    APP_NAME: str = "Agoreum API"
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"

    # --- Database ------------------------------------------------------------
    # Async driver URL used by the application at runtime.
    DATABASE_URL: str = "postgresql+asyncpg://agoreum:agoreum@localhost:5432/agoreum"
    # Sync driver URL used by Alembic migrations.
    DATABASE_URL_SYNC: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # --- Redis ---------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Security / auth -----------------------------------------------------
    JWT_SECRET: SecretStr = SecretStr("")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    SIWE_DOMAIN: str = "localhost:3000"
    SIWE_STATEMENT: str = "Sign in to Agoreum. This request will not trigger a blockchain transaction or cost any gas."
    SIWE_NONCE_TTL_SECONDS: int = 600

    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    RATE_LIMIT_PER_MINUTE: int = 60

    # --- Blockchain (Base) ---------------------------------------------------
    CHAIN_ID: int = 8453
    ALCHEMY_API_KEY: SecretStr = SecretStr("")
    ALCHEMY_BASE_URL: SecretStr = SecretStr("")
    USDC_CONTRACT_ADDRESS_BASE: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    ESCROW_CONTRACT_ADDRESS: str | None = None

    # --- Email (Resend) ------------------------------------------------------
    RESEND_API_KEY: SecretStr = SecretStr("")
    EMAIL_FROM: str = "support@agoreum.xyz"
    SUPPORT_EMAIL: str = "support@agoreum.xyz"

    # --- Observability -------------------------------------------------------
    SENTRY_DSN: SecretStr | None = None

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string from the environment."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Alembic, derived from the async URL when not set explicitly."""
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        return self.DATABASE_URL.replace("+asyncpg", "").replace(
            "postgresql://", "postgresql+psycopg://", 1
        )


@functools.lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
