"""Response models for the operational surface."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class DisputeQueueItem(BaseModel):
    """One dispute waiting on the arbiter.

    `hours_waiting` is included rather than left to the reader to compute from a
    timestamp, because the queue is ordered by it and the thing being decided is
    somebody's money held while they wait.
    """

    order_id: uuid.UUID
    order_reference: str
    amount: Decimal
    currency: str
    disputed_at: datetime | None
    hours_waiting: int | None
    reason: str | None


class SuppressionView(BaseModel):
    email: str
    reason: str
    detail: str | None
    created_at: datetime


class ReputationExclusionRequest(BaseModel):
    """Why an order must not count toward its provider's standing.

    The reason is required and has a floor length on purpose. This decision is
    irreversible by construction, so the only thing a future reader has to go on
    is what was written at the time, and "test" would leave them nothing.
    """

    reason: str = Field(min_length=12, max_length=2000)


class ReputationExclusionView(BaseModel):
    order_id: uuid.UUID
    order_reference: str
    provider_agent_id: uuid.UUID
    reputation_excluded_at: datetime
    reputation_exclusion_reason: str


class ReputationRecomputeView(BaseModel):
    agent_slug: str
    computed_at: datetime
    completed_orders: int
    total_volume: Decimal
    score: Decimal | None
