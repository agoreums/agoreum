"""Creator analytics: combine settled-order metrics with Umami pageviews."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import OrderStatus
from app.modules.agents.models import Agent
from app.modules.analytics import umami
from app.modules.analytics.schemas import CreatorAnalytics, ViewsPoint
from app.modules.orders.models import Order
from app.modules.users.models import User

# The platform settles in USDC; every order carries it, so it is the reporting unit.
CURRENCY = "USDC"


async def creator_analytics(
    db: AsyncSession, *, user: User, window_days: int = 30
) -> CreatorAnalytics:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    agents = (
        await db.execute(select(Agent.id, Agent.slug).where(Agent.owner_id == user.id))
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
    )
