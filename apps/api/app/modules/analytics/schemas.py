"""Response models for creator analytics."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ViewsPoint(BaseModel):
    date: date
    views: int


class CreatorAnalytics(BaseModel):
    """Analytics for the signed-in creator, over a trailing window.

    `views` and `conversion_rate` are null when the view data source is not
    configured or reachable, rather than reported as zero, so a missing data source
    is never mistaken for genuinely zero traffic. Every other figure comes from real,
    settled orders.
    """

    window_days: int
    # From Umami pageviews of the creator's agent and service pages.
    views: int | None
    views_series: list[ViewsPoint] | None
    # From settled orders on the creator's agents.
    purchases: int
    revenue: Decimal
    currency: str
    repeat_customers: int
    # purchases / views, null when views are unavailable or zero.
    conversion_rate: float | None
