"""Creator analytics endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.modules.analytics import service
from app.modules.analytics.schemas import BuyerAnalytics, CreatorAnalytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/me", response_model=CreatorAnalytics, summary="Your creator analytics")
async def my_analytics(
    user: CurrentUser,
    db: DbSession,
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> CreatorAnalytics:
    """Views, purchases, revenue, repeat customers, and conversion for the agents
    you own, over a trailing window. View-based figures are null when the analytics
    data source is unavailable rather than reported as zero."""
    return await service.creator_analytics(db, user=user, window_days=window_days)


@router.get(
    "/me/purchases",
    response_model=BuyerAnalytics,
    summary="Your buying activity",
)
async def my_purchase_analytics(
    user: CurrentUser,
    db: DbSession,
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> BuyerAnalytics:
    """What you have spent and what is still in flight.

    Spend is the total charged, including the platform fee, because that is what
    left your wallet. The creator figure uses the subtotal instead, since the fee
    is not theirs to count.
    """
    return await service.buyer_analytics(db, user=user, window_days=window_days)
