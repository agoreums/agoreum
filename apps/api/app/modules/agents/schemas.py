"""Request and response models for agents."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import AgentStatus, AgentVerificationTier
from app.modules.agents.capabilities import AgentCapabilities

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# Slugs that would collide with routes or impersonate the platform.
RESERVED_SLUGS = frozenset(
    {
        "admin", "agoreum", "api", "app", "auth", "billing", "dashboard", "docs",
        "help", "login", "logout", "marketplace", "new", "official", "register",
        "root", "search", "security", "settings", "signin", "signup", "support",
        "system", "team", "terms", "privacy", "www",
    }
)

Slug = Annotated[str, Field(min_length=2, max_length=64)]


def validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            "Must be 2-64 characters: lowercase letters, numbers and hyphens, "
            "starting with a letter or number."
        )
    if slug in RESERVED_SLUGS:
        raise ValueError("This name is reserved.")
    return slug


class AgentCreate(BaseModel):
    slug: Slug
    name: str = Field(min_length=2, max_length=96)
    tagline: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=8000)
    website_url: str | None = Field(default=None, max_length=512)
    avatar_url: str | None = Field(default=None, max_length=512)
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    api_endpoint: str | None = Field(default=None, max_length=512)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return validate_slug(v)

    @field_validator("website_url", "avatar_url", "api_endpoint")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        """Reject anything that is not an absolute HTTPS URL.

        Blocks `javascript:` and `data:` payloads that would otherwise be
        rendered into a link, and prevents plaintext callbacks for agent APIs.
        """
        if v is None or not v.strip():
            return None
        url = v.strip()
        if not url.startswith("https://"):
            raise ValueError("Must be an absolute https:// URL.")
        if len(url) > 512:
            raise ValueError("URL is too long.")
        return url


class AgentUpdate(BaseModel):
    """Partial update. Every field is optional; omitted fields are left alone.

    `slug` and `owner` are deliberately absent: a slug is a public identifier
    others may already link to, and ownership transfer is a separate,
    deliberate operation rather than a field edit.
    """

    name: str | None = Field(default=None, min_length=2, max_length=96)
    tagline: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=8000)
    website_url: str | None = Field(default=None, max_length=512)
    avatar_url: str | None = Field(default=None, max_length=512)
    capabilities: AgentCapabilities | None = None
    api_endpoint: str | None = Field(default=None, max_length=512)

    @field_validator("website_url", "avatar_url", "api_endpoint")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        url = v.strip()
        if not url.startswith("https://"):
            raise ValueError("Must be an absolute https:// URL.")
        return url


class AgentPayoutUpdate(BaseModel):
    wallet_id: uuid.UUID


class AgentPublic(BaseModel):
    """An agent as seen by anyone.

    Reputation figures are included only as counts of real, terminal activity.
    `average_rating` is null rather than zero when an agent has never been
    reviewed, because unrated is not the same as badly rated.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    tagline: str | None
    description: str | None
    avatar_url: str | None
    website_url: str | None
    status: AgentStatus
    verification_tier: AgentVerificationTier
    verified_domain: str | None
    verified_github: str | None
    capabilities: AgentCapabilities
    api_endpoint: str | None
    payout_address: str | None
    completed_orders: int
    cancelled_orders: int
    disputed_orders: int
    review_count: int
    average_rating: float | None
    published_at: datetime | None
    last_active_at: datetime | None
    created_at: datetime


class AgentOwnerView(AgentPublic):
    """Adds fields only the owner should see."""

    owner_id: uuid.UUID
    payout_wallet_id: uuid.UUID | None
    updated_at: datetime


class AgentListItem(BaseModel):
    """A compact projection for listings, to avoid shipping full descriptions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    tagline: str | None
    avatar_url: str | None
    status: AgentStatus
    verification_tier: AgentVerificationTier
    completed_orders: int
    review_count: int
    average_rating: float | None


class DomainChallengeCreate(BaseModel):
    domain: str = Field(min_length=4, max_length=253)
    method: str = Field(default="dns_txt", pattern="^(dns_txt|well_known)$")

    @field_validator("domain")
    @classmethod
    def _clean_domain(cls, v: str) -> str:
        """Normalise to a bare hostname.

        Accepting a full URL and silently verifying only its host would be
        misleading, so the input is reduced to the host and validated as one.
        """
        domain = v.strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("/")[0].split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        if not re.match(
            r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$", domain
        ):
            raise ValueError("Not a valid domain name.")
        return domain


class DomainChallengeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    method: str
    token: str
    expires_at: datetime
    verified_at: datetime | None
    attempt_count: int
    last_error: str | None
    # Exactly what the operator has to publish, so there is no guesswork.
    instructions: str | None = None


class GithubChallengeCreate(BaseModel):
    # A GitHub username, @handle, or profile URL. Normalised in the service.
    github_login: str = Field(min_length=1, max_length=120)


class GithubChallengeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_login: str
    token: str
    expires_at: datetime
    verified_at: datetime | None
    attempt_count: int
    last_error: str | None
    instructions: str | None = None


class PaginatedAgents(BaseModel):
    items: list[AgentListItem]
    total: int
    limit: int
    offset: int
