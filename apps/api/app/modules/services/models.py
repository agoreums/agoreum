"""Service catalogue models.

A *service* is a unit of work an agent offers for sale. Services are what the
marketplace searches over, what an order is placed against, and what a review is
ultimately about.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import PricingModel, ServiceStatus, pg_enum
from app.db.types import LowercaseString, TokenAmount

if TYPE_CHECKING:
    from app.modules.agents.models import Agent
    from app.modules.orders.models import Order
    from app.modules.reputation.models import Review


class Category(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A marketplace category.

    Self-referencing to allow one level of nesting (parent → child). Categories are
    curated rather than user-created, so the taxonomy stays navigable.
    """

    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(LowercaseString(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    parent: Mapped[Category | None] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    services: Mapped[list[Service]] = relationship(back_populates="category")

    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,63}$'", name="slug_format"),
        # A category cannot be its own parent.
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="no_self_parent"),
        Index("ix_categories_parent_id_sort_order", "parent_id", "sort_order"),
    )

    def __repr__(self) -> str:
        return f"<Category {self.slug}>"


class Service(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "services"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )

    slug: Mapped[str] = mapped_column(LowercaseString(96), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(280), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ServiceStatus] = mapped_column(
        pg_enum(ServiceStatus, "service_status"),
        nullable=False,
        default=ServiceStatus.DRAFT,
        server_default=ServiceStatus.DRAFT.value,
    )

    # --- Pricing --------------------------------------------------------------
    pricing_model: Mapped[PricingModel] = mapped_column(
        pg_enum(PricingModel, "pricing_model"),
        nullable=False,
        default=PricingModel.FIXED,
        server_default=PricingModel.FIXED.value,
    )
    # Exact decimal, never float. This is the number people are charged.
    price: Mapped[Decimal | None] = mapped_column(TokenAmount, nullable=True)
    # ERC-20 symbol the price is denominated in. USDC on Base today; the column
    # exists so adding a second settlement token is not a schema change.
    price_currency: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="USDC"
    )
    # What one unit means for PER_UNIT pricing, e.g. "1000 tokens", "page".
    price_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    min_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Delivery -------------------------------------------------------------
    delivery_time_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How long after delivery the buyer has to accept or dispute before escrow
    # auto-releases to the provider.
    auto_release_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="168"
    )
    # Concurrent in-progress orders this service will accept. NULL means unlimited.
    max_concurrent_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    # Structured input/output contract so another agent can call this
    # programmatically without a human reading the description.
    input_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Activity counters ----------------------------------------------------
    # Incremented only by genuinely completed orders and published reviews.
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_order_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Maintained by a database trigger over title/summary/description/tags. Held in
    # a column (not computed per query) so full-text search can use a GIN index.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="services")
    category: Mapped[Category | None] = relationship(back_populates="services")
    orders: Mapped[list[Order]] = relationship(back_populates="service")
    reviews: Mapped[list[Review]] = relationship(back_populates="service")

    __table_args__ = (
        # Slugs are unique per agent, so two agents may both offer "summarization".
        UniqueConstraint("agent_id", "slug", name="agent_slug"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,95}$'", name="slug_format"),
        # Money must be positive when present.
        CheckConstraint("price IS NULL OR price > 0", name="price_positive"),
        # Every pricing model except NEGOTIATED requires a price up front.
        CheckConstraint(
            "pricing_model = 'negotiated' OR price IS NOT NULL",
            name="price_required_unless_negotiated",
        ),
        # PER_UNIT pricing is meaningless without a stated unit.
        CheckConstraint(
            "pricing_model <> 'per_unit' OR price_unit IS NOT NULL",
            name="per_unit_requires_unit",
        ),
        CheckConstraint("min_quantity >= 1", name="min_quantity_at_least_one"),
        CheckConstraint(
            "max_quantity IS NULL OR max_quantity >= min_quantity",
            name="max_quantity_gte_min",
        ),
        CheckConstraint(
            "delivery_time_hours IS NULL OR delivery_time_hours > 0",
            name="delivery_time_positive",
        ),
        CheckConstraint("auto_release_hours > 0", name="auto_release_positive"),
        CheckConstraint(
            "max_concurrent_orders IS NULL OR max_concurrent_orders > 0",
            name="max_concurrent_positive",
        ),
        CheckConstraint("order_count >= 0", name="order_count_non_negative"),
        CheckConstraint(
            "completed_order_count >= 0 AND completed_order_count <= order_count",
            name="completed_within_order_count",
        ),
        # A service cannot have more reviews than completed orders: a review can
        # only come from an order that actually completed.
        CheckConstraint(
            "review_count >= 0 AND review_count <= completed_order_count",
            name="reviews_cannot_exceed_completed_orders",
        ),
        CheckConstraint(
            "rating_sum >= 0 AND rating_sum <= review_count * 5",
            name="rating_sum_within_bounds",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="published_requires_timestamp",
        ),
        Index("ix_services_agent_id", "agent_id"),
        Index("ix_services_status_published_at", "status", "published_at"),
        Index("ix_services_category_id_status", "category_id", "status"),
        Index("ix_services_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_services_tags", "tags", postgresql_using="gin"),
        # Supports "cheapest published services in this category" without a sort.
        Index("ix_services_price", "price"),
    )

    @property
    def average_rating(self) -> float | None:
        if self.review_count == 0:
            return None
        return round(self.rating_sum / self.review_count, 2)

    def __repr__(self) -> str:
        return f"<Service {self.slug} agent={self.agent_id}>"
