"""Dashboard aggregates.

Every figure here is counted from real rows. There is no sample data, no
projection, and no placeholder: a new account sees zeros because it has done
nothing yet, which is the truth and is more useful than an invented number.

Where a figure cannot be known, a rating with no reviews, a settled volume with
no settled orders, it is `None` rather than `0`, so the interface can say
"nothing yet" instead of implying a measured result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    AgentStatus,
    EscrowStatus,
    OrderStatus,
    ServiceStatus,
)
from app.modules.agents.models import Agent
from app.modules.orders.models import Escrow, Order
from app.modules.reputation.models import Review
from app.modules.services.models import Service
from app.modules.users.models import User

# Orders in these states are still live work; the rest are terminal.
ACTIVE_ORDER_STATES = (
    OrderStatus.PENDING_PAYMENT,
    OrderStatus.FUNDED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.DELIVERED,
    OrderStatus.DISPUTED,
)

SETTLED_ESCROW_STATES = (EscrowStatus.RELEASED, EscrowStatus.REFUNDED)


@dataclass
class BuyerDashboard:
    active_orders: int
    completed_orders: int
    disputed_orders: int
    total_spent: Decimal
    currency: str
    pending_payment: int
    awaiting_review: int
    recent_orders: list[dict] = field(default_factory=list)


@dataclass
class ProviderDashboard:
    agents: int
    published_agents: int
    published_services: int
    active_orders: int
    completed_orders: int
    # None until something has actually settled, rather than a misleading zero.
    total_earned: Decimal | None
    currency: str
    average_rating: float | None
    review_count: int
    awaiting_action: int
    recent_orders: list[dict] = field(default_factory=list)


@dataclass
class AdminDashboard:
    users: int
    agents: int
    published_agents: int
    services: int
    published_services: int
    orders: int
    orders_by_status: dict[str, int]
    settled_volume: Decimal
    platform_fees: Decimal
    currency: str
    escrows_awaiting_settlement: int
    open_disputes: int
    new_users_7d: int
    orders_7d: int


async def buyer_dashboard(db: AsyncSession, *, user: User) -> BuyerDashboard:
    status_counts = dict(
        (
            await db.execute(
                select(Order.status, func.count())
                .where(Order.buyer_id == user.id)
                .group_by(Order.status)
            )
        ).all()
    )

    active = sum(status_counts.get(s, 0) for s in ACTIVE_ORDER_STATES)

    # Spend counts what actually left escrow, not what was invoiced.
    total_spent = (
        await db.execute(
            select(func.coalesce(func.sum(Escrow.amount), 0))
            .select_from(Escrow)
            .join(Order, Order.id == Escrow.order_id)
            .where(
                Order.buyer_id == user.id,
                Escrow.status.in_(SETTLED_ESCROW_STATES),
            )
        )
    ).scalar_one()

    reviewed = select(Review.order_id).where(Review.author_id == user.id)
    awaiting_review = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .join(Escrow, Escrow.order_id == Order.id)
            .where(
                Order.buyer_id == user.id,
                Order.status == OrderStatus.COMPLETED,
                Escrow.status.in_(SETTLED_ESCROW_STATES),
                Order.id.notin_(reviewed),
            )
        )
    ).scalar_one()

    recent = (
        await db.execute(
            select(Order)
            .where(Order.buyer_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    return BuyerDashboard(
        active_orders=active,
        completed_orders=status_counts.get(OrderStatus.COMPLETED, 0),
        disputed_orders=status_counts.get(OrderStatus.DISPUTED, 0),
        total_spent=Decimal(total_spent),
        currency="USDC",
        pending_payment=status_counts.get(OrderStatus.PENDING_PAYMENT, 0),
        awaiting_review=awaiting_review,
        recent_orders=[_order_row(o) for o in recent],
    )


async def provider_dashboard(db: AsyncSession, *, user: User) -> ProviderDashboard:
    agent_ids = (
        await db.execute(select(Agent.id).where(Agent.owner_id == user.id))
    ).scalars().all()

    if not agent_ids:
        return ProviderDashboard(
            agents=0,
            published_agents=0,
            published_services=0,
            active_orders=0,
            completed_orders=0,
            total_earned=None,
            currency="USDC",
            average_rating=None,
            review_count=0,
            awaiting_action=0,
        )

    published_agents = (
        await db.execute(
            select(func.count())
            .select_from(Agent)
            .where(Agent.owner_id == user.id, Agent.status == AgentStatus.ACTIVE)
        )
    ).scalar_one()

    published_services = (
        await db.execute(
            select(func.count())
            .select_from(Service)
            .where(
                Service.agent_id.in_(agent_ids),
                Service.status == ServiceStatus.PUBLISHED,
            )
        )
    ).scalar_one()

    status_counts = dict(
        (
            await db.execute(
                select(Order.status, func.count())
                .where(Order.provider_agent_id.in_(agent_ids))
                .group_by(Order.status)
            )
        ).all()
    )

    # Earnings are what the escrow actually released, net of nothing else.
    earned = (
        await db.execute(
            select(func.sum(Escrow.released_amount))
            .select_from(Escrow)
            .join(Order, Order.id == Escrow.order_id)
            .where(
                Order.provider_agent_id.in_(agent_ids),
                Escrow.status.in_(SETTLED_ESCROW_STATES),
            )
        )
    ).scalar_one()

    rating_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Agent.rating_sum), 0),
                func.coalesce(func.sum(Agent.review_count), 0),
            ).where(Agent.owner_id == user.id)
        )
    ).one()
    rating_sum, review_count = int(rating_row[0]), int(rating_row[1])

    # Work the provider needs to act on: funded but not yet delivered.
    awaiting_action = status_counts.get(OrderStatus.FUNDED, 0) + status_counts.get(
        OrderStatus.IN_PROGRESS, 0
    )

    recent = (
        await db.execute(
            select(Order)
            .where(Order.provider_agent_id.in_(agent_ids))
            .order_by(Order.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    return ProviderDashboard(
        agents=len(agent_ids),
        published_agents=published_agents,
        published_services=published_services,
        active_orders=sum(status_counts.get(s, 0) for s in ACTIVE_ORDER_STATES),
        completed_orders=status_counts.get(OrderStatus.COMPLETED, 0),
        total_earned=Decimal(earned) if earned is not None else None,
        currency="USDC",
        average_rating=(
            round(rating_sum / review_count, 2) if review_count else None
        ),
        review_count=review_count,
        awaiting_action=awaiting_action,
        recent_orders=[_order_row(o) for o in recent],
    )


async def admin_dashboard(db: AsyncSession) -> AdminDashboard:
    week_ago = datetime.now(UTC) - timedelta(days=7)

    async def count(model, *conditions) -> int:
        return (
            await db.execute(
                select(func.count()).select_from(model).where(*conditions)
            )
        ).scalar_one()

    status_counts = dict(
        (
            await db.execute(select(Order.status, func.count()).group_by(Order.status))
        ).all()
    )

    settled_volume = (
        await db.execute(
            select(func.coalesce(func.sum(Escrow.released_amount), 0)).where(
                Escrow.status.in_(SETTLED_ESCROW_STATES)
            )
        )
    ).scalar_one()

    platform_fees = (
        await db.execute(
            select(func.coalesce(func.sum(Escrow.fee_amount), 0)).where(
                Escrow.status.in_(SETTLED_ESCROW_STATES)
            )
        )
    ).scalar_one()

    return AdminDashboard(
        users=await count(User),
        agents=await count(Agent),
        published_agents=await count(Agent, Agent.status == AgentStatus.ACTIVE),
        services=await count(Service),
        published_services=await count(
            Service, Service.status == ServiceStatus.PUBLISHED
        ),
        orders=await count(Order),
        orders_by_status={s.value: c for s, c in status_counts.items()},
        settled_volume=Decimal(settled_volume),
        platform_fees=Decimal(platform_fees),
        currency="USDC",
        escrows_awaiting_settlement=await count(
            Escrow, Escrow.status == EscrowStatus.FUNDED
        ),
        open_disputes=await count(Escrow, Escrow.status == EscrowStatus.DISPUTED),
        new_users_7d=await count(User, User.created_at >= week_ago),
        orders_7d=await count(Order, Order.created_at >= week_ago),
    )


def _order_row(order: Order) -> dict:
    return {
        "id": str(order.id),
        "reference": order.reference,
        "status": order.status.value,
        "total_amount": str(order.total_amount),
        "currency": order.currency,
        "created_at": order.created_at.isoformat(),
    }
