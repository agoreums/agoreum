"""Subscription plan catalogue, status, history, and subscribe instructions.

Reads of a user's subscriptions are a read of what the indexer projected from the
chain. Nothing here activates a subscription; that only happens when a confirmed
`Subscribed` event is applied by the indexer.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chain import subscriptions as contract
from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.subscriptions.models import (
    Subscription,
    SubscriptionPayment,
    SubscriptionPlan,
)
from app.modules.subscriptions.schemas import PlanCreate, PlanUpdate
from app.modules.users.models import User, Wallet

# --- Plan catalogue ---------------------------------------------------------


async def list_plans(db: AsyncSession, *, active_only: bool = True) -> list[SubscriptionPlan]:
    stmt = select(SubscriptionPlan).order_by(SubscriptionPlan.price)
    if active_only:
        stmt = stmt.where(SubscriptionPlan.active.is_(True))
    return list((await db.execute(stmt)).scalars())


async def get_plan(db: AsyncSession, *, plan_id: int) -> SubscriptionPlan | None:
    return (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.plan_id == plan_id)
        )
    ).scalar_one_or_none()


async def create_plan(db: AsyncSession, *, payload: PlanCreate) -> SubscriptionPlan:
    if await get_plan(db, plan_id=payload.plan_id) is not None:
        raise ConflictError(
            f"A plan with id {payload.plan_id} already exists.", code="plan_exists"
        )
    plan = SubscriptionPlan(
        plan_id=payload.plan_id,
        name=payload.name,
        description=payload.description,
        tier=payload.tier,
        interval=payload.interval,
        token_address=payload.token_address.lower(),
        token_symbol=payload.token_symbol,
        token_decimals=payload.token_decimals,
        price=payload.price,
        period_seconds=payload.period_seconds,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def update_plan(
    db: AsyncSession, *, plan_id: int, payload: PlanUpdate
) -> SubscriptionPlan:
    plan = await get_plan(db, plan_id=plan_id)
    if plan is None:
        raise NotFoundError("No such plan.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


# --- A user's subscriptions -------------------------------------------------


async def _user_addresses(db: AsyncSession, user: User) -> list[str]:
    rows = (
        await db.execute(select(Wallet.address).where(Wallet.user_id == user.id))
    ).scalars()
    addresses = {a.lower() for a in rows}
    addresses.add(user.primary_address.lower())
    return list(addresses)


async def get_user_subscriptions(
    db: AsyncSession, *, user: User
) -> list[tuple[Subscription, SubscriptionPlan | None]]:
    addresses = await _user_addresses(db, user)
    subs = (
        await db.execute(
            select(Subscription)
            .where(
                or_(
                    Subscription.user_id == user.id,
                    Subscription.subscriber_address.in_(addresses),
                )
            )
            .order_by(Subscription.current_period_end.desc())
        )
    ).scalars()
    subs = list(subs)

    plan_ids = {s.plan_id for s in subs}
    plans = {
        p.plan_id: p
        for p in (
            await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.plan_id.in_(plan_ids))
            )
        ).scalars()
    }
    return [(s, plans.get(s.plan_id)) for s in subs]


async def list_user_payments(
    db: AsyncSession, *, user: User, limit: int
) -> list[SubscriptionPayment]:
    addresses = await _user_addresses(db, user)
    rows = (
        await db.execute(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.subscriber_address.in_(addresses))
            .order_by(SubscriptionPayment.block_number.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)


# --- Subscribe instructions -------------------------------------------------


async def subscribe_instructions(db: AsyncSession, *, plan_id: int) -> dict:
    if not contract.is_configured():
        raise contract.SubscriptionsNotConfiguredError()
    plan = await get_plan(db, plan_id=plan_id)
    if plan is None:
        raise NotFoundError("No such plan.")
    if not plan.active:
        raise ValidationError("This plan is not currently available.", code="plan_inactive")

    price_units = str(contract.to_base_units(plan.price))
    return {
        "chain_id": settings.CHAIN_ID,
        "subscription_contract": contract.contract_address(),
        "plan_id": plan.plan_id,
        "token_address": plan.token_address,
        "token_symbol": plan.token_symbol,
        "token_decimals": plan.token_decimals,
        "price": plan.price,
        "price_base_units": price_units,
        "max_price_base_units": price_units,
        "note": (
            "Approve the subscription contract to spend the price on the token, "
            "then call subscribe(planId, maxPrice). Agoreum never signs or holds "
            "funds; your wallet sends both transactions."
        ),
    }
