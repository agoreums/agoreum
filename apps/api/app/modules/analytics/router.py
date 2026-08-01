"""Creator analytics endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.modules.analytics import service
from app.modules.analytics.schemas import CreatorAnalytics

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
