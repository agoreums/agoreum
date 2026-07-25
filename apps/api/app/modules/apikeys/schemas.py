"""Request and response models for API keys."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.apikeys.scopes import SCOPES


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # Left empty, the key gets the default read-only marketplace scope rather than
    # everything: a key should never be more powerful than its creator asked for.
    scopes: list[str] = Field(default_factory=list)
    # Optional lifetime in days. Omitted means the key does not expire on its own
    # and must be revoked explicitly.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyPublic(BaseModel):
    """A key's metadata. Never carries the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyPublic):
    """The one and only response that includes the secret, returned at creation.

    The plaintext key is shown here once and never again; only its hash is stored.
    """

    token: str


class ApiKeyList(BaseModel):
    items: list[ApiKeyPublic]
    total: int


class ScopeInfo(BaseModel):
    scope: str
    description: str


class ScopeCatalog(BaseModel):
    """The scopes a key may be granted, for the management UI and the docs."""

    scopes: list[ScopeInfo] = [
        ScopeInfo(scope=s, description=d) for s, d in SCOPES.items()
    ]
