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
    # Defaults to on, so a deployment that forgets to configure it is still
    # protected. Turned off in local development and in the test suite, where
    # hundreds of sign-ins from one address would otherwise throttle the run.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60

    # --- Blockchain (Base) ---------------------------------------------------
    # Base mainnet (8453) or Base Sepolia (84532). Everything chain-specific is
    # selected from this one value rather than being configured twice.
    CHAIN_ID: int = 84532

    ALCHEMY_API_KEY: SecretStr = SecretStr("")
    # Full RPC endpoints, one per network. These are complete URLs including the
    # API key, which is how Alchemy issues them.
    ALCHEMY_BASE_URL_MAINNET: SecretStr = SecretStr("")
    ALCHEMY_BASE_URL_SEPOLIA: SecretStr = SecretStr("")

    # USDC is deployed at a different address on each network. Sending funds to
    # the mainnet address on testnet (or the reverse) would be unrecoverable, so
    # the pairing is resolved from CHAIN_ID rather than configured by hand.
    USDC_ADDRESS_BASE_MAINNET: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    USDC_ADDRESS_BASE_SEPOLIA: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

    ESCROW_CONTRACT_ADDRESS: str | None = None

    # Confirmations before an on-chain event is treated as settled. Base is an
    # L2 with fast blocks; this is depth, not time.
    CHAIN_CONFIRMATIONS: int = 5

    # --- Email (Resend) ------------------------------------------------------
    RESEND_API_KEY: SecretStr = SecretStr("")
    EMAIL_FROM: str = "support@agoreum.xyz"
    SUPPORT_EMAIL: str = "support@agoreum.xyz"

    # Master switch for outbound email. Defaults to off so that running the
    # suite, or a developer exercising a flow locally, cannot put real messages
    # in real inboxes. Delivery is still recorded — as suppressed, with the
    # reason — so the intent is visible without anyone being contacted.
    EMAIL_SENDING_ENABLED: bool = False

    # --- Observability -------------------------------------------------------
    SENTRY_DSN: SecretStr | None = None

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string from the environment."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # --- Chain resolution ----------------------------------------------------

    BASE_MAINNET_CHAIN_ID: int = 8453
    BASE_SEPOLIA_CHAIN_ID: int = 84532

    @property
    def is_mainnet(self) -> bool:
        return self.CHAIN_ID == self.BASE_MAINNET_CHAIN_ID

    @property
    def rpc_url(self) -> str:
        """The RPC endpoint for the configured chain.

        Returns an empty string when unconfigured rather than falling back to a
        public endpoint: silently using a different provider would make the
        source of chain data ambiguous at exactly the moment it matters.
        """
        secret = (
            self.ALCHEMY_BASE_URL_MAINNET
            if self.is_mainnet
            else self.ALCHEMY_BASE_URL_SEPOLIA
        )
        return secret.get_secret_value()

    @property
    def usdc_address(self) -> str:
        """USDC for the configured chain."""
        return (
            self.USDC_ADDRESS_BASE_MAINNET
            if self.is_mainnet
            else self.USDC_ADDRESS_BASE_SEPOLIA
        )

    @property
    def chain_name(self) -> str:
        return "Base" if self.is_mainnet else "Base Sepolia"

    @property
    def explorer_url(self) -> str:
        return "https://basescan.org" if self.is_mainnet else "https://sepolia.basescan.org"

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
