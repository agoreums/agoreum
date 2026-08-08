"""Creator analytics: combine settled-order metrics with Umami pageviews."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import OrderStatus
from app.modules.agents.models import Agent
from app.modules.analytics import umami
from app.modules.analytics.schemas import (
    BuyerAnalytics,
    CreatorAnalytics,
    Pipeline,
    RevenuePoint,
    Trend,
    ViewsPoint,
)
from app.modules.orders.models import Order
from app.modules.organizations.models import OrganizationMembership
from app.modules.users.models import User

# The platform settles in USDC; every order carries it, so it is the reporting unit.
CURRENCY = "USDC"



# Funded and being worked on. Money is committed but not earned, so these are
# reported apart from revenue rather than added to it.
ACTIVE_STATUSES = (
    OrderStatus.FUNDED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.DELIVERED,
)


def _change_pct(current: Decimal | int, previous: Decimal | int) -> float | None:
    """Percentage change, or None when the comparison would be meaningless.

    Growth from zero has no percentage. Reporting one anyway, as an infinity or a
    flat hundred, reads as a real measurement and is not one.
    """
    if not previous:
        return None
    return round(float((Decimal(str(current)) - Decimal(str(previous))) / Decimal(str(previous)) * 100), 1)


async def _sum_and_count(db: AsyncSession, condition) -> tuple[int, Decimal]:
    row = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.subtotal), 0)).where(condition)
        )
    ).one()
    return int(row[0]), Decimal(str(row[1]))


async def _daily_revenue(
    db: AsyncSession, condition, cutoff: datetime
) -> list[RevenuePoint]:
    """Settled revenue per day.

    Days with no settlement are absent rather than zero-filled; the caller plots
    a sparse series, and inventing rows here would make an empty window look like
    a run of genuine zeroes.
    """
    rows = (
        await db.execute(
            select(
                func.date(Order.completed_at).label("day"),
                func.coalesce(func.sum(Order.subtotal), 0),
            )
            .where(condition)
            .group_by(func.date(Order.completed_at))
            .order_by(func.date(Order.completed_at))
        )
    ).all()
    return [RevenuePoint(date=r[0], revenue=Decimal(str(r[1]))) for r in rows]


async def creator_analytics(
    db: AsyncSession, *, user: User, window_days: int = 30
) -> CreatorAnalytics:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    # Every agent across every organization the user belongs to.
    agents = (
        await db.execute(
            select(Agent.id, Agent.slug)
            .join(
                OrganizationMembership,
                OrganizationMembership.org_id == Agent.org_id,
            )
            .where(OrganizationMembership.user_id == user.id)
        )
    ).all()
    agent_ids = [a.id for a in agents]
    agent_slugs = [a.slug for a in agents]

    if not agent_ids:
        views = await umami.total_pageviews([], cutoff)
        return CreatorAnalytics(
            window_days=window_days,
            views=views,
            views_series=None,
            purchases=0,
            revenue=Decimal("0"),
            currency=CURRENCY,
            repeat_customers=0,
            conversion_rate=None,
            revenue_series=[],
            pipeline=Pipeline(
                active_orders=0,
                active_value=Decimal("0"),
                disputed_orders=0,
                disputed_value=Decimal("0"),
                refunded_orders=0,
                refunded_value=Decimal("0"),
            ),
            trend=Trend(
                purchases=0,
                revenue=Decimal("0"),
                purchases_change_pct=None,
                revenue_change_pct=None,
            ),
        )

    # An order counts only when it actually settled in the window. The provider's
    # earning is the subtotal; the platform fee is separate and not revenue to them.
    settled = (
        (Order.provider_agent_id.in_(agent_ids))
        & (Order.status == OrderStatus.COMPLETED)
        & (Order.completed_at >= cutoff)
    )

    purchases = (
        await db.execute(select(func.count()).select_from(Order).where(settled))
    ).scalar_one()
    revenue = (
        await db.execute(select(func.coalesce(func.sum(Order.subtotal), 0)).where(settled))
    ).scalar_one()

    # A repeat customer is a buyer with more than one settled order in the window.
    per_buyer = (
        select(Order.buyer_id)
        .where(settled)
        .group_by(Order.buyer_id)
        .having(func.count() > 1)
        .subquery()
    )
    repeat_customers = (
        await db.execute(select(func.count()).select_from(per_buyer))
    ).scalar_one()

    views = await umami.total_pageviews(agent_slugs, cutoff)
    series = await umami.daily_pageviews(agent_slugs, cutoff)

    conversion_rate: float | None = None
    if views is not None and views > 0:
        conversion_rate = round(purchases / views, 4)

    revenue_series = await _daily_revenue(db, settled, cutoff)

    # In flight right now, regardless of when it started. This is a snapshot of
    # exposure rather than a windowed figure: an order funded two months ago and
    # still unresolved is exactly what a provider needs to see.
    by_agent = Order.provider_agent_id.in_(agent_ids)
    active_orders, active_value = await _sum_and_count(
        db, by_agent & Order.status.in_(ACTIVE_STATUSES)
    )
    disputed_orders, disputed_value = await _sum_and_count(
        db, by_agent & (Order.status == OrderStatus.DISPUTED)
    )
    refunded_orders, refunded_value = await _sum_and_count(
        db,
        by_agent
        & (Order.status == OrderStatus.REFUNDED)
        & (Order.updated_at >= cutoff),
    )

    # The window immediately before this one, same length, so the comparison is
    # like for like.
    previous_cutoff = cutoff - timedelta(days=window_days)
    previous_purchases, previous_revenue = await _sum_and_count(
        db,
        by_agent
        & (Order.status == OrderStatus.COMPLETED)
        & (Order.completed_at >= previous_cutoff)
        & (Order.completed_at < cutoff),
    )

    return CreatorAnalytics(
        window_days=window_days,
        views=views,
        views_series=(
            [ViewsPoint(date=d, views=v) for d, v in series] if series is not None else None
        ),
        purchases=purchases,
        revenue=Decimal(str(revenue)),
        currency=CURRENCY,
        repeat_customers=repeat_customers,
        conversion_rate=conversion_rate,
        revenue_series=revenue_series,
        pipeline=Pipeline(
            active_orders=active_orders,
            active_value=active_value,
            disputed_orders=disputed_orders,
            disputed_value=disputed_value,
            refunded_orders=refunded_orders,
            refunded_value=refunded_value,
        ),
        trend=Trend(
            purchases=previous_purchases,
            revenue=previous_revenue,
            purchases_change_pct=_change_pct(purchases, previous_purchases),
            revenue_change_pct=_change_pct(Decimal(str(revenue)), previous_revenue),
        ),
    )


async def buyer_analytics(
    db: AsyncSession, *, user: User, window_days: int = 30
) -> BuyerAnalytics:
    """What this account has spent, and what is still in flight.

    The counterpart to creator analytics, and it did not exist: the platform
    could tell a provider what they had earned but could tell a buyer nothing
    about what they had committed.

    Spend is the total charged, so it includes the platform fee, which is the
    figure a buyer actually paid. Creator revenue deliberately uses the subtotal
    instead, since the fee is not theirs. Two different questions, two different
    numbers, and conflating them would misreport both.
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    mine = Order.buyer_id == user.id

    settled = mine & (Order.status == OrderStatus.COMPLETED) & (Order.completed_at >= cutoff)
    row = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_amount), 0)).where(settled)
        )
    ).one()
    orders, spend = int(row[0]), Decimal(str(row[1]))

    active = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_amount), 0)).where(
                mine & Order.status.in_(ACTIVE_STATUSES)
            )
        )
    ).one()

    disputed = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .where(mine & (Order.status == OrderStatus.DISPUTED))
        )
    ).scalar_one()

    providers = (
        await db.execute(
            select(func.count(func.distinct(Order.provider_agent_id))).where(settled)
        )
    ).scalar_one()

    return BuyerAnalytics(
        window_days=window_days,
        currency=CURRENCY,
        orders=orders,
        spend=spend,
        active_orders=int(active[0]),
        active_value=Decimal(str(active[1])),
        disputed_orders=int(disputed),
        providers_used=int(providers),
    )
