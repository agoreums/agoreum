"""Search and discovery request/response models."""
from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.db.enums import AgentVerificationTier, PricingModel
from app.modules.services.schemas import ServiceListItem

MAX_PAGE_SIZE = 60
DEFAULT_PAGE_SIZE = 20
# Long queries are almost always paste accidents, and they make ranking useless.
MAX_QUERY_LENGTH = 200


class ServiceSort(StrEnum):
    """How results are ordered.

    `RELEVANCE` is only meaningful when there is a text query; with no query it
    falls back to a deterministic ordering rather than pretending to rank.
    """

    RELEVANCE = "relevance"
    NEWEST = "newest"
    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    MOST_COMPLETED = "most_completed"
    TOP_RATED = "top_rated"


class AgentSort(StrEnum):
    NEWEST = "newest"
    MOST_COMPLETED = "most_completed"
    TOP_RATED = "top_rated"


class ServiceSearchParams(BaseModel):
    """Filters for the service marketplace.

    Every filter narrows a real query. None of them are advisory.
    """

    q: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)
    category: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=8)
    pricing_model: PricingModel | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    max_delivery_hours: int | None = Field(default=None, ge=1, le=8760)
    verification_tier: AgentVerificationTier | None = None
    # Filters to services whose provider has at least this mean rating. Services
    # with no reviews are excluded when this is set, because an unrated provider
    # cannot be said to meet a rating floor.
    min_rating: float | None = Field(default=None, ge=1, le=5)
    agent: str | None = Field(default=None, max_length=64)
    sort: ServiceSort = ServiceSort.RELEVANCE
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("q")
    @classmethod
    def _clean_query(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = " ".join(v.split())
        return cleaned or None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        return [t.strip().lower() for t in v if t.strip()][:8]


class AgentSearchParams(BaseModel):
    q: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)
    verification_tier: AgentVerificationTier | None = None
    min_rating: float | None = Field(default=None, ge=1, le=5)
    sort: AgentSort = AgentSort.MOST_COMPLETED
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("q")
    @classmethod
    def _clean_query(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = " ".join(v.split())
        return cleaned or None


class CategoryFacet(BaseModel):
    """A category and how many results actually fall in it.

    Counts come from the same filtered query as the results, so a facet never
    promises more than clicking it would return.
    """

    slug: str
    name: str
    count: int


class ServiceSearchResults(BaseModel):
    items: list[ServiceListItem]
    total: int
    limit: int
    offset: int
    query: str | None = None
    sort: ServiceSort
    # Present only when the caller asked for them; an empty list means no
    # matching results in any category, not "facets unavailable".
    facets: list[CategoryFacet] | None = None


class AgentSearchItem(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    tagline: str | None
    avatar_url: str | None
    verification_tier: AgentVerificationTier
    verified_domain: str | None
    completed_orders: int
    review_count: int
    average_rating: float | None
    published_service_count: int


class AgentSearchResults(BaseModel):
    items: list[AgentSearchItem]
    total: int
    limit: int
    offset: int
    query: str | None = None
    sort: AgentSort
