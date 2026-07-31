"""Reputation models.

Reputation on Agoreum is derived, never issued. Two structural guarantees enforce
that at the database level rather than by convention:

1. A `Review` requires an `order_id`, that order must have reached `COMPLETED`, and
   there can be at most one review per order. There is no code path that creates a
   review without a real, paid, completed engagement behind it.
2. `ReputationSnapshot` rows are computed aggregates over that activity. They are
   caches with a recorded computation time, not an independent source of truth, so
   they can always be rebuilt from the underlying orders and reviews.

There is no field anywhere that lets a score be set directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import ReviewStatus, pg_enum
from app.db.types import TokenAmount

if TYPE_CHECKING:
    from app.modules.agents.models import Agent
    from app.modules.orders.models import Order
    from app.modules.services.models import Service
    from app.modules.users.models import User


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A buyer's review of a completed order.

    The unique constraint on `order_id` is what makes review-stuffing structurally
    impossible: one completed order yields at most one review, forever.
    """

    __tablename__ = "reviews"

    # NOT NULL and UNIQUE: every review is anchored to exactly one real order.
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subject_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )

    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ReviewStatus] = mapped_column(
        pg_enum(ReviewStatus, "review_status"),
        nullable=False,
        default=ReviewStatus.PUBLISHED,
        server_default=ReviewStatus.PUBLISHED.value,
    )

    # The provider's single public reply.
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removal_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    order: Mapped[Order] = relationship(back_populates="review")
    author: Mapped[User] = relationship(
        back_populates="reviews_written", foreign_keys=[author_id]
    )
    subject_agent: Mapped[Agent] = relationship(foreign_keys=[subject_agent_id])
    service: Mapped[Service] = relationship(back_populates="reviews")

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_in_range"),
        CheckConstraint(
            "(response_body IS NULL) = (response_at IS NULL)",
            name="response_consistent",
        ),
        CheckConstraint(
            "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)",
            name="withdrawn_at_matches_status",
        ),
        CheckConstraint(
            "(status = 'removed') = (removed_at IS NOT NULL)",
            name="removed_at_matches_status",
        ),
        Index("ix_reviews_subject_agent_id_status", "subject_agent_id", "status"),
        Index("ix_reviews_service_id_status", "service_id", "status"),
        Index("ix_reviews_author_id", "author_id"),
        Index("ix_reviews_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Review order={self.order_id} rating={self.rating}>"


class ReputationSnapshot(Base, UUIDPrimaryKeyMixin):
    """A point-in-time computed reputation for an agent.

    Every field is an aggregate over completed orders and published reviews. The
    snapshot exists so ranking and profile reads are fast and so reputation history
    is visible over time, not as a place where a score can be authored.
    """

    __tablename__ = "reputation_snapshots"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    # --- Inputs (all counts of real, terminal activity) -----------------------
    completed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cancelled_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    disputed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    disputes_lost: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Settled volume, in the settlement currency. Only released escrow counts.
    total_volume: Mapped[Decimal] = mapped_column(
        TokenAmount, nullable=False, server_default="0"
    )
    volume_currency: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="USDC"
    )

    # Median hours from funding to delivery. NULL until there is data.
    median_delivery_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    on_time_delivery_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )

    # --- Derived score --------------------------------------------------------
    # 0..100. NULL when the agent has too little activity for a score to mean
    # anything, an honest absence rather than a misleading default.
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Identifies the formula that produced `score`, so historical snapshots remain
    # interpretable after the algorithm changes.
    algorithm_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="v1"
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    agent: Mapped[Agent] = relationship(back_populates="reputation_snapshots")

    __table_args__ = (
        CheckConstraint("completed_orders >= 0", name="completed_non_negative"),
        CheckConstraint("cancelled_orders >= 0", name="cancelled_non_negative"),
        CheckConstraint("disputed_orders >= 0", name="disputed_non_negative"),
        CheckConstraint(
            "disputes_lost >= 0 AND disputes_lost <= disputed_orders",
            name="disputes_lost_within_disputed",
        ),
        CheckConstraint("review_count >= 0", name="review_count_non_negative"),
        CheckConstraint(
            "rating_sum >= 0 AND rating_sum <= review_count * 5",
            name="rating_sum_within_bounds",
        ),
        CheckConstraint("total_volume >= 0", name="volume_non_negative"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)", name="score_in_range"
        ),
        CheckConstraint(
            "on_time_delivery_rate IS NULL"
            " OR (on_time_delivery_rate >= 0 AND on_time_delivery_rate <= 1)",
            name="on_time_rate_in_range",
        ),
        CheckConstraint(
            "median_delivery_hours IS NULL OR median_delivery_hours >= 0",
            name="median_delivery_non_negative",
        ),
        # One snapshot per agent per computation instant.
        UniqueConstraint("agent_id", "computed_at", name="agent_computed_at"),
        Index("ix_reputation_snapshots_agent_id_computed_at", "agent_id", "computed_at"),
        Index("ix_reputation_snapshots_score", "score"),
    )

    @property
    def average_rating(self) -> float | None:
        if self.review_count == 0:
            return None
        return round(self.rating_sum / self.review_count, 2)

    def __repr__(self) -> str:
        return f"<ReputationSnapshot agent={self.agent_id} score={self.score}>"
