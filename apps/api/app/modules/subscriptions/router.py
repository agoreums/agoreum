"""Subscription endpoints: the public plan catalogue, a user's own status and
payment history, subscribe instructions, and admin plan management."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.modules.subscriptions import service
from app.modules.subscriptions.schemas import (
    PaymentPublic,
    PlanCreate,
    PlanPublic,
    PlanUpdate,
    SubscribeInstructions,
    SubscriptionPublic,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[PlanPublic], summary="Available plans")
async def list_plans(db: DbSession) -> list[PlanPublic]:
    plans = await service.list_plans(db, active_only=True)
    return [PlanPublic.model_validate(p) for p in plans]


@router.get(
    "/plans/{plan_id}/instructions",
    response_model=SubscribeInstructions,
    summary="How to subscribe to a plan from your wallet",
)
async def instructions(plan_id: int, db: DbSession) -> SubscribeInstructions:
    data = await service.subscribe_instructions(db, plan_id=plan_id)
    return SubscribeInstructions(**data)


@router.get("/me", response_model=list[SubscriptionPublic], summary="Your subscriptions")
async def my_subscriptions(user: CurrentUser, db: DbSession) -> list[SubscriptionPublic]:
    pairs = await service.get_user_subscriptions(db, user=user)
    return [
        SubscriptionPublic(
            plan_id=sub.plan_id,
            tier=plan.tier if plan else "",
            status=sub.status,
            subscriber_address=sub.subscriber_address,
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            auto_renew_cancelled=sub.auto_renew_cancelled,
            plan=PlanPublic.model_validate(plan) if plan else None,
        )
        for sub, plan in pairs
    ]


@router.get(
    "/me/payments", response_model=list[PaymentPublic], summary="Your payment history"
)
async def my_payments(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[PaymentPublic]:
    payments = await service.list_user_payments(db, user=user, limit=limit)
    return [PaymentPublic.model_validate(p) for p in payments]


# --- Admin plan management --------------------------------------------------


@router.post(
    "/plans",
    response_model=PlanPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a plan (admin)",
)
async def create_plan(payload: PlanCreate, _: AdminUser, db: DbSession) -> PlanPublic:
    plan = await service.create_plan(db, payload=payload)
    return PlanPublic.model_validate(plan)


@router.patch(
    "/plans/{plan_id}", response_model=PlanPublic, summary="Update a plan (admin)"
)
async def update_plan(
    plan_id: int, payload: PlanUpdate, _: AdminUser, db: DbSession
) -> PlanPublic:
    plan = await service.update_plan(db, plan_id=plan_id, payload=payload)
    return PlanPublic.model_validate(plan)
