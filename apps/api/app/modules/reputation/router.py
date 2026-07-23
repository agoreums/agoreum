"""Review and reputation endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.modules.agents import service as agent_service
from app.modules.orders import service as order_service
from app.modules.reputation import service
from app.modules.reputation.models import Review
from app.modules.reputation.schemas import (
    PaginatedReviews,
    ReputationReport,
    ReviewableOrder,
    ReviewCreate,
    ReviewPublic,
    ReviewResponse,
)

router = APIRouter(tags=["reputation"])


@router.get(
    "/agents/{slug}/reputation",
    response_model=ReputationReport,
    summary="An agent's reputation and the facts behind it",
)
async def agent_reputation(slug: str, db: DbSession) -> ReputationReport:
    """Returns the score together with every input it was computed from, so a
    provider can see why it is what it is and anyone can check the arithmetic."""
    agent = await agent_service.require_agent(db, slug)

    snapshot = await service.latest_snapshot(db, agent_id=agent.id)
    if snapshot is None:
        # Nothing computed yet — compute it now rather than reporting zeros.
        snapshot = await service.recompute(db, agent_id=agent.id)

    note = None
    if snapshot.score is None:
        if snapshot.completed_orders == 0:
            note = (
                "This agent has not completed any settled orders yet, so there "
                "is nothing to score."
            )
        else:
            note = (
                f"A score is published after "
                f"{service.MIN_ORDERS_FOR_SCORE} settled orders. This agent has "
                f"{snapshot.completed_orders}."
            )

    return ReputationReport(
        agent_id=agent.id,
        agent_slug=agent.slug,
        score=snapshot.score,
        algorithm_version=snapshot.algorithm_version,
        computed_at=snapshot.computed_at,
        completed_orders=snapshot.completed_orders,
        cancelled_orders=snapshot.cancelled_orders,
        disputed_orders=snapshot.disputed_orders,
        disputes_lost=snapshot.disputes_lost,
        review_count=snapshot.review_count,
        average_rating=snapshot.average_rating,
        total_volume=snapshot.total_volume,
        volume_currency=snapshot.volume_currency,
        median_delivery_hours=snapshot.median_delivery_hours,
        on_time_delivery_rate=snapshot.on_time_delivery_rate,
        note=note,
    )


@router.get(
    "/agents/{slug}/reviews",
    response_model=PaginatedReviews,
    summary="Reviews of an agent",
)
async def agent_reviews(
    slug: str,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PaginatedReviews:
    agent = await agent_service.require_agent(db, slug)
    reviews, total = await service.list_for_agent(
        db, agent_id=agent.id, limit=limit, offset=offset
    )
    return PaginatedReviews(
        items=[ReviewPublic.model_validate(r) for r in reviews],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/reviews/pending",
    response_model=list[ReviewableOrder],
    summary="Your settled orders awaiting a review",
)
async def pending_reviews(
    user: CurrentUser, db: DbSession
) -> list[ReviewableOrder]:
    """Only completed orders whose escrow actually settled appear here."""
    orders = await service.reviewable_orders(db, user=user)
    return [ReviewableOrder.model_validate(o) for o in orders]


@router.post(
    "/reviews",
    response_model=ReviewPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Review a completed order",
)
async def create_review(
    payload: ReviewCreate, user: CurrentUser, db: DbSession
) -> ReviewPublic:
    """Requires a completed order, settled on-chain, reviewed once, by its buyer.

    Those four gates are what make reputation a record of real trade rather
    than an opinion poll.
    """
    order = await order_service.require_visible_order(db, payload.order_id, user=user)
    review = await service.create_review(
        db,
        order=order,
        author=user,
        rating=payload.rating,
        title=payload.title,
        body=payload.body,
    )
    return ReviewPublic.model_validate(review)


@router.post(
    "/reviews/{review_id}/response",
    response_model=ReviewPublic,
    summary="Provider: reply to a review",
)
async def respond(
    review_id: uuid.UUID,
    payload: ReviewResponse,
    user: CurrentUser,
    db: DbSession,
) -> ReviewPublic:
    review = (
        await db.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("No such review.")

    updated = await service.respond_to_review(
        db, review=review, responder=user, body=payload.body
    )
    return ReviewPublic.model_validate(updated)


@router.delete(
    "/reviews/{review_id}",
    response_model=ReviewPublic,
    summary="Withdraw your review",
)
async def withdraw(
    review_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ReviewPublic:
    """Withdrawing removes the review's contribution to the agent's score."""
    review = (
        await db.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("No such review.")

    updated = await service.withdraw_review(db, review=review, author=user)
    return ReviewPublic.model_validate(updated)
