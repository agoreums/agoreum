"""Response models for creator analytics."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ViewsPoint(BaseModel):
    date: date
    views: int


class RevenuePoint(BaseModel):
    """Settled revenue for one day."""

    date: date
    revenue: Decimal


class Pipeline(BaseModel):
    """Work and money that has not settled yet.

    Separate from revenue on purpose. Escrow that is funded but not released is
    not earnings, and reporting the two together would overstate what a provider
    actually has. Disputed is broken out because it is the number that warrants
    acting on today.
    """

    active_orders: int
    active_value: Decimal
    disputed_orders: int
    disputed_value: Decimal
    refunded_orders: int
    refunded_value: Decimal


class Trend(BaseModel):
    """The same window immediately before this one, for comparison.

    A bare total says nothing about direction. Percentages are omitted rather
    than invented when the previous period was zero, since growth from nothing
    has no meaningful percentage.
    """

    purchases: int
    revenue: Decimal
    purchases_change_pct: float | None
    revenue_change_pct: float | None


class BuyerAnalytics(BaseModel):
    """What a buyer has spent and what is still in flight."""

    window_days: int
    currency: str
    orders: int
    spend: Decimal
    active_orders: int
    active_value: Decimal
    disputed_orders: int
    providers_used: int


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
    revenue_series: list[RevenuePoint]
    pipeline: Pipeline
    trend: Trend
