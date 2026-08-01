"""Request and response models for authentication."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import UserRole, WalletProvider
from app.db.types import is_evm_address


class NonceRequest(BaseModel):
    address: str | None = Field(
        default=None,
        description=(
            "Optional wallet address. When supplied, the nonce is bound to it and "
            "cannot be spent by a different wallet."
        ),
    )
    chain_id: int | None = Field(default=None, ge=1)

    @field_validator("address")
    @classmethod
    def _valid_address(cls, v: str | None) -> str | None:
        if v is not None and not is_evm_address(v):
            raise ValueError("Not a valid EVM address")
        return v.lower() if v else None


class NonceResponse(BaseModel):
    nonce: str
    expires_at: datetime
    # The exact message to sign, returned only when an address was supplied.
    # Server-built so the statement a user approves is always one we authored.
    message: str | None = None


class SignInRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=4096,
        description="The full EIP-4361 message that was signed.",
    )
    signature: str = Field(min_length=1, max_length=1024)
    nonce: str = Field(min_length=1, max_length=96)
    wallet_provider: WalletProvider = WalletProvider.OTHER


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    # S105 flags the name; this is the OAuth2 scheme label, not a credential.
    token_type: str = "Bearer"  # noqa: S105
    expires_at: datetime
    refresh_expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(
        default=None,
        max_length=512,
        description="Omit to revoke only the current session's access token family.",
    )
    all_sessions: bool = False


class WalletSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    chain_id: int
    label: str | None
    provider: WalletProvider
    verification_status: str
    verified_at: datetime | None
    is_payout: bool


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    primary_address: str
    username: str | None
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    email: str | None
    email_verified_at: datetime | None
    role: UserRole
    status: str
    preferred_locale: str
    created_at: datetime
    last_seen_at: datetime | None


# The locales the product ships. A preferred locale must be one of these so the
# value stored server-side (used for notification and email language) is always
# something the platform can actually render.
SUPPORTED_LOCALES = frozenset(
    {"en", "es", "fr", "de", "pt", "ar", "zh", "ja", "ko"}
)
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")


class ProfileUpdate(BaseModel):
    """A partial update to the signed-in user's own profile.

    Every field is optional. A field that is present is applied, a field that is
    absent is left untouched, and an explicit null clears the value where the
    column allows it. Validation mirrors the database constraints so a bad value
    is refused with a clear message rather than a database error.
    """

    username: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=600)
    avatar_url: str | None = Field(default=None, max_length=512)
    email: str | None = Field(default=None, max_length=320)
    preferred_locale: str | None = Field(default=None, max_length=10)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if not _USERNAME_RE.match(v):
            raise ValueError(
                "A username is 3 to 32 characters: lowercase letters, numbers, "
                "hyphens and underscores, starting with a letter or number."
            )
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if "@" not in v or v.startswith("@") or "." not in v.split("@")[-1]:
            raise ValueError("That does not look like an email address.")
        return v

    @field_validator("avatar_url")
    @classmethod
    def _avatar(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith("https://"):
            raise ValueError("An avatar URL must be an absolute https:// URL.")
        return v

    @field_validator("display_name", "bio")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("preferred_locale")
    @classmethod
    def _locale(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in SUPPORTED_LOCALES:
            raise ValueError("That language is not supported.")
        return v


class SignInResponse(BaseModel):
    user: UserProfile
    tokens: TokenResponse


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    chain_id: int
    user_agent: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


class AuthCapabilities(BaseModel):
    """What this deployment can actually verify.

    Reported honestly: if EIP-1271 verification is unavailable the client is told,
    rather than discovering it when a smart-contract wallet fails to sign in.
    """

    siwe_domain: str
    accepted_chain_ids: list[int]
    contract_wallets_supported: bool
    nonce_ttl_seconds: int
