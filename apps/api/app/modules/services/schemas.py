"""Request and response models for the service catalogue."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import PricingModel, ServiceStatus
from app.modules.agents.schemas import validate_slug

# USDC has 6 decimals. A price with more precision than the settlement token can
# represent would be quietly truncated on chain, so it is rejected instead.
TOKEN_DECIMALS = 6
MAX_PRICE = Decimal("1000000")

Price = Annotated[Decimal, Field(gt=0, le=MAX_PRICE)]


def _check_price_precision(value: Decimal) -> Decimal:
    if value.as_tuple().exponent < -TOKEN_DECIMALS:
        raise ValueError(
            f"Price cannot have more than {TOKEN_DECIMALS} decimal places."
        )
    return value


class ServiceBase(BaseModel):
    title: str = Field(min_length=4, max_length=128)
    summary: str | None = Field(default=None, max_length=280)
    description: str | None = Field(default=None, max_length=16000)
    category_id: uuid.UUID | None = None
    pricing_model: PricingModel = PricingModel.FIXED
    price: Price | None = None
    price_unit: str | None = Field(default=None, max_length=32)
    min_quantity: int = Field(default=1, ge=1, le=10000)
    max_quantity: int | None = Field(default=None, ge=1, le=10000)
    delivery_time_hours: int | None = Field(default=None, ge=1, le=8760)
    auto_release_hours: int = Field(default=168, ge=1, le=8760)
    max_concurrent_orders: int | None = Field(default=None, ge=1, le=1000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    @field_validator("price")
    @classmethod
    def _price_precision(cls, v: Decimal | None) -> Decimal | None:
        return _check_price_precision(v) if v is not None else None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        """Normalise, deduplicate, and bound tags.

        Tags feed the search index and the filter UI, so uncontrolled variants
        of the same word would fragment both.
        """
        cleaned: list[str] = []
        for tag in v:
            normalised = tag.strip().lower()
            if not normalised:
                continue
            if len(normalised) > 32:
                raise ValueError("Each tag must be 32 characters or fewer.")
            if not all(c.isalnum() or c in "-_ " for c in normalised):
                raise ValueError(
                    "Tags may contain only letters, numbers, spaces, hyphens "
                    "and underscores."
                )
            if normalised not in cleaned:
                cleaned.append(normalised)
        return cleaned

    @model_validator(mode="after")
    def _coherent_pricing(self) -> ServiceBase:
        """Reject pricing that cannot be acted on.

        These mirror database CHECK constraints. Validating here as well turns a
        constraint violation into a clear, field-level message.
        """
        if self.pricing_model != PricingModel.NEGOTIATED and self.price is None:
            raise ValueError(
                "A price is required unless the pricing model is 'negotiated'."
            )
        if self.pricing_model == PricingModel.PER_UNIT and not self.price_unit:
            raise ValueError(
                "Per-unit pricing needs a unit, for example '1000 tokens'."
            )
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("Maximum quantity cannot be below the minimum.")
        return self


class ServiceCreate(ServiceBase):
    slug: str = Field(min_length=2, max_length=96)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return validate_slug(v)


class ServiceUpdate(BaseModel):
    """Partial update. The slug is immutable once published."""

    title: str | None = Field(default=None, min_length=4, max_length=128)
    summary: str | None = Field(default=None, max_length=280)
    description: str | None = Field(default=None, max_length=16000)
    category_id: uuid.UUID | None = None
    pricing_model: PricingModel | None = None
    price: Price | None = None
    price_unit: str | None = Field(default=None, max_length=32)
    min_quantity: int | None = Field(default=None, ge=1, le=10000)
    max_quantity: int | None = Field(default=None, ge=1, le=10000)
    delivery_time_hours: int | None = Field(default=None, ge=1, le=8760)
    auto_release_hours: int | None = Field(default=None, ge=1, le=8760)
    max_concurrent_orders: int | None = Field(default=None, ge=1, le=1000)
    tags: list[str] | None = Field(default=None, max_length=12)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    @field_validator("price")
    @classmethod
    def _price_precision(cls, v: Decimal | None) -> Decimal | None:
        return _check_price_precision(v) if v is not None else None


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    parent_id: uuid.UUID | None


class CategoryTree(CategorySummary):
    children: list[CategorySummary] = Field(default_factory=list)


class ServiceAgentSummary(BaseModel):
    """The provider, as shown on a service listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    avatar_url: str | None
    verification_tier: str
    completed_orders: int
    average_rating: float | None


class ServicePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    description: str | None
    status: ServiceStatus
    pricing_model: PricingModel
    price: Decimal | None
    price_currency: str
    price_unit: str | None
    min_quantity: int
    max_quantity: int | None
    delivery_time_hours: int | None
    auto_release_hours: int
    tags: list[str]
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    # Counts of genuinely completed work. Zero means zero, not "unknown".
    order_count: int
    completed_order_count: int
    review_count: int
    average_rating: float | None
    published_at: datetime | None
    created_at: datetime


class ServiceDetail(ServicePublic):
    agent: ServiceAgentSummary
    category: CategorySummary | None


class ServiceOwnerView(ServicePublic):
    agent_id: uuid.UUID
    category_id: uuid.UUID | None
    max_concurrent_orders: int | None
    updated_at: datetime


class ServiceListItem(BaseModel):
    """Compact projection for listings and search results."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    pricing_model: PricingModel
    price: Decimal | None
    price_currency: str
    price_unit: str | None
    delivery_time_hours: int | None
    tags: list[str]
    completed_order_count: int
    review_count: int
    average_rating: float | None
    agent: ServiceAgentSummary


class PaginatedServices(BaseModel):
    items: list[ServiceListItem]
    total: int
    limit: int
    offset: int
    # Echoed back so a client can render "showing results for…" truthfully.
    query: str | None = None
