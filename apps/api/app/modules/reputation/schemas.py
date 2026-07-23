"""Request and response models for reviews and reputation."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    order_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, max_length=4_000)


class ReviewResponse(BaseModel):
    body: str = Field(min_length=1, max_length=4_000)


class ReviewPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    subject_agent_id: uuid.UUID
    service_id: uuid.UUID
    rating: int
    title: str | None
    body: str | None
    response_body: str | None
    response_at: datetime | None
    created_at: datetime


class PaginatedReviews(BaseModel):
    items: list[ReviewPublic]
    total: int
    limit: int
    offset: int


class ReputationReport(BaseModel):
    """An agent's reputation, with the facts it was computed from.

    The inputs are returned alongside the score so a provider can see exactly
    why it is what it is, and anyone can check the arithmetic.
    """

    agent_id: uuid.UUID
    agent_slug: str

    # Null when there is too little settled history for a score to mean
    # anything. Unrated is not the same as badly rated.
    score: Decimal | None
    algorithm_version: str
    computed_at: datetime | None

    completed_orders: int
    cancelled_orders: int
    disputed_orders: int
    disputes_lost: int
    review_count: int
    average_rating: float | None
    total_volume: Decimal
    volume_currency: str
    median_delivery_hours: Decimal | None
    on_time_delivery_rate: Decimal | None

    # Says plainly why no score is published, rather than showing a bare null.
    note: str | None = None


class ReviewableOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    service_id: uuid.UUID
    provider_agent_id: uuid.UUID
    total_amount: Decimal
    currency: str
    completed_at: datetime | None
