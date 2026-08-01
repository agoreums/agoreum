"""Reputation, derived entirely from completed and settled activity.

Two rules govern everything here:

1. **Only settled work counts.** An order contributes to reputation when it has
   reached `COMPLETED` *and* its escrow has actually released or settled on
   chain. An order marked complete without money having moved contributes
   nothing, because nothing real happened.
2. **Scores are computed, never assigned.** There is no function that sets a
   score, and no argument anywhere that could carry one. Every figure is
   recomputed from orders and reviews, so a snapshot can always be rebuilt and
   checked against its inputs.

A provider with too little history has a score of `None`, not zero. Unrated and
badly rated are different facts, and collapsing them would slander every new
agent on the platform.
"""
from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.db.enums import EscrowStatus, OrderStatus, ReviewStatus
from app.modules.agents.models import Agent
from app.modules.orders.models import Escrow, Order
from app.modules.organizations.authz import is_member
from app.modules.reputation.models import ReputationSnapshot, Review
from app.modules.services.models import Service
from app.modules.users.models import User

logger = get_logger(__name__)

ALGORITHM_VERSION = "v1"

# Below this many settled orders a score would say more about small numbers than
# about the provider, so none is published.
MIN_ORDERS_FOR_SCORE = 3

# Escrow states that mean money actually moved to the provider.
SETTLED_ESCROW_STATES = (EscrowStatus.RELEASED, EscrowStatus.REFUNDED)


@dataclass(frozen=True)
class ReputationInputs:
    """The raw, verifiable facts a score is computed from."""

    completed_orders: int
    cancelled_orders: int
    disputed_orders: int
    disputes_lost: int
    review_count: int
    rating_sum: int
    total_volume: Decimal
    median_delivery_hours: Decimal | None
    on_time_delivery_rate: Decimal | None

    @property
    def average_rating(self) -> Decimal | None:
        if self.review_count == 0:
            return None
        return Decimal(self.rating_sum) / Decimal(self.review_count)

    @property
    def has_enough_history(self) -> bool:
        return self.completed_orders >= MIN_ORDERS_FOR_SCORE


# --- Gathering the facts ----------------------------------------------------


async def gather_inputs(db: AsyncSession, *, agent_id: uuid.UUID) -> ReputationInputs:
    """Read every figure a score depends on, straight from orders and reviews.

    Deliberately recomputed rather than read from cached counters: the counters
    exist to make reads fast, and this is what proves they are still right.
    """
    settled = (
        select(Order)
        .join(Escrow, Escrow.order_id == Order.id)
        .where(
            Order.provider_agent_id == agent_id,
            Order.status == OrderStatus.COMPLETED,
            # The order says complete *and* the chain says the money moved.
            Escrow.status.in_(SETTLED_ESCROW_STATES),
            Escrow.released_amount > 0,
        )
    ).subquery()

    completed_orders = (
        await db.execute(select(func.count()).select_from(settled))
    ).scalar_one()

    cancelled_orders = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.provider_agent_id == agent_id,
                Order.status.in_([OrderStatus.CANCELLED, OrderStatus.REFUNDED]),
            )
        )
    ).scalar_one()

    disputed_orders = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .join(Escrow, Escrow.order_id == Order.id)
            .where(
                Order.provider_agent_id == agent_id,
                Escrow.disputed_at.isnot(None),
            )
        )
    ).scalar_one()

    # A dispute is "lost" when the buyer got money back from the settlement.
    disputes_lost = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .join(Escrow, Escrow.order_id == Order.id)
            .where(
                Order.provider_agent_id == agent_id,
                Escrow.disputed_at.isnot(None),
                Escrow.refunded_amount > 0,
            )
        )
    ).scalar_one()

    # Volume is what actually reached the provider, not what was invoiced.
    total_volume = (
        await db.execute(
            select(func.coalesce(func.sum(Escrow.released_amount), 0))
            .select_from(Escrow)
            .join(Order, Order.id == Escrow.order_id)
            .where(
                Order.provider_agent_id == agent_id,
                Escrow.status.in_(SETTLED_ESCROW_STATES),
            )
        )
    ).scalar_one()

    review_stats = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Review.rating), 0))
            .select_from(Review)
            .where(
                Review.subject_agent_id == agent_id,
                Review.status == ReviewStatus.PUBLISHED,
            )
        )
    ).one()

    median_hours, on_time_rate = await _delivery_metrics(db, agent_id=agent_id)

    return ReputationInputs(
        completed_orders=completed_orders,
        cancelled_orders=cancelled_orders,
        disputed_orders=disputed_orders,
        disputes_lost=disputes_lost,
        review_count=review_stats[0],
        rating_sum=int(review_stats[1]),
        total_volume=Decimal(total_volume),
        median_delivery_hours=median_hours,
        on_time_delivery_rate=on_time_rate,
    )


async def _delivery_metrics(
    db: AsyncSession, *, agent_id: uuid.UUID
) -> tuple[Decimal | None, Decimal | None]:
    """Median delivery time and on-time rate, or None when there is no data.

    Computed in Python from real timestamps rather than in SQL, because a median
    over a small set is clearer here and the row count is bounded by the agent's
    own completed orders.
    """
    rows = (
        await db.execute(
            select(
                Order.funded_at,
                Order.delivered_at,
                Service.delivery_time_hours,
            )
            .join(Service, Service.id == Order.service_id)
            .where(
                Order.provider_agent_id == agent_id,
                Order.status == OrderStatus.COMPLETED,
                Order.funded_at.isnot(None),
                Order.delivered_at.isnot(None),
            )
        )
    ).all()

    if not rows:
        return None, None

    durations: list[float] = []
    on_time = 0
    measurable = 0

    for funded_at, delivered_at, promised_hours in rows:
        hours = (delivered_at - funded_at).total_seconds() / 3600
        durations.append(hours)
        if promised_hours is not None:
            measurable += 1
            if hours <= promised_hours:
                on_time += 1

    median = Decimal(str(round(statistics.median(durations), 2)))
    rate = (
        Decimal(str(round(on_time / measurable, 4))) if measurable else None
    )
    return median, rate


# --- Scoring ----------------------------------------------------------------


def compute_score(inputs: ReputationInputs) -> Decimal | None:
    """Turn verified activity into a 0-100 score, or None when unknowable.

    The weighting is deliberately simple and explainable, because a provider is
    entitled to understand why their score is what it is:

    * satisfaction (60), mean review rating, the buyers' own verdict
    * reliability   (25), completed against everything that reached a terminal
                           state, so cancellations and refunds count against it
    * disputes      (15), lost disputes only; raising one is not a fault

    Returns None below `MIN_ORDERS_FOR_SCORE`. A number derived from one or two
    orders would be noise presented as a fact.
    """
    if not inputs.has_enough_history:
        return None

    terminal = (
        inputs.completed_orders + inputs.cancelled_orders + inputs.disputes_lost
    )
    reliability = (
        Decimal(inputs.completed_orders) / Decimal(terminal) if terminal else Decimal(1)
    )

    # With settled work but no reviews yet, satisfaction is unknown and is
    # treated as neutral rather than assumed good or bad. Otherwise the 1..5
    # rating scale is mapped onto 0..1.
    average = inputs.average_rating
    satisfaction = (
        Decimal("0.6") if average is None else (average - Decimal(1)) / Decimal(4)
    )

    if inputs.disputed_orders == 0:
        dispute_health = Decimal(1)
    else:
        dispute_health = Decimal(1) - (
            Decimal(inputs.disputes_lost) / Decimal(inputs.disputed_orders)
        )

    score = (
        satisfaction * Decimal(60)
        + reliability * Decimal(25)
        + dispute_health * Decimal(15)
    )
    return score.quantize(Decimal("0.01"))


async def recompute(db: AsyncSession, *, agent_id: uuid.UUID) -> ReputationSnapshot:
    """Recompute an agent's reputation and record a snapshot.

    Also refreshes the cached counters on the agent row, so the fast read path
    and the authoritative computation cannot drift apart.
    """
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError("No such agent.")

    inputs = await gather_inputs(db, agent_id=agent_id)
    score = compute_score(inputs)

    agent.completed_orders = inputs.completed_orders
    agent.cancelled_orders = inputs.cancelled_orders
    agent.disputed_orders = inputs.disputed_orders
    agent.review_count = inputs.review_count
    agent.rating_sum = inputs.rating_sum

    snapshot = ReputationSnapshot(
        agent_id=agent_id,
        completed_orders=inputs.completed_orders,
        cancelled_orders=inputs.cancelled_orders,
        disputed_orders=inputs.disputed_orders,
        disputes_lost=inputs.disputes_lost,
        review_count=inputs.review_count,
        rating_sum=inputs.rating_sum,
        total_volume=inputs.total_volume,
        median_delivery_hours=inputs.median_delivery_hours,
        on_time_delivery_rate=inputs.on_time_delivery_rate,
        score=score,
        algorithm_version=ALGORITHM_VERSION,
        computed_at=datetime.now(UTC),
    )
    db.add(snapshot)
    await db.flush()

    logger.info(
        "reputation_recomputed",
        extra={
            "agent_id": str(agent_id),
            "score": str(score) if score is not None else None,
            "completed_orders": inputs.completed_orders,
        },
    )
    return snapshot


async def latest_snapshot(
    db: AsyncSession, *, agent_id: uuid.UUID
) -> ReputationSnapshot | None:
    return (
        await db.execute(
            select(ReputationSnapshot)
            .where(ReputationSnapshot.agent_id == agent_id)
            .order_by(ReputationSnapshot.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# --- Reviews ----------------------------------------------------------------


async def create_review(
    db: AsyncSession,
    *,
    order: Order,
    author: User,
    rating: int,
    title: str | None,
    body: str | None,
) -> Review:
    """Record a buyer's review of a completed order.

    Every gate here is a structural guarantee that reputation reflects real
    trade: only the buyer, only after completion, only once, and only when the
    escrow actually released.
    """
    if order.buyer_id != author.id:
        raise PermissionDeniedError("Only the buyer can review this order.")

    if order.status != OrderStatus.COMPLETED:
        raise ConflictError(
            "Only a completed order can be reviewed.", code="order_not_completed"
        )

    escrow = order.escrow
    if escrow is None or escrow.status not in SETTLED_ESCROW_STATES:
        # The order says complete but the chain has not settled it. Allowing a
        # review here would let reputation be built on unpaid work.
        raise ConflictError(
            "This order has not settled on-chain yet, so it cannot be reviewed.",
            code="order_not_settled",
        )

    review = Review(
        order_id=order.id,
        author_id=author.id,
        subject_agent_id=order.provider_agent_id,
        service_id=order.service_id,
        rating=rating,
        title=title,
        body=body,
        status=ReviewStatus.PUBLISHED,
    )
    db.add(review)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # The unique constraint on order_id is what makes review-stuffing
        # impossible; it is the authority, not a prior existence check.
        raise ConflictError(
            "This order has already been reviewed.", code="already_reviewed"
        ) from exc

    service = (
        await db.execute(select(Service).where(Service.id == order.service_id))
    ).scalar_one()
    service.review_count += 1
    service.rating_sum += rating

    await recompute(db, agent_id=order.provider_agent_id)
    await db.flush()

    logger.info(
        "review_created",
        extra={"order": str(order.id), "agent": str(order.provider_agent_id)},
    )
    return review


async def respond_to_review(
    db: AsyncSession, *, review: Review, responder: User, body: str
) -> Review:
    """Let the provider reply once, publicly."""
    agent = (
        await db.execute(select(Agent).where(Agent.id == review.subject_agent_id))
    ).scalar_one()

    if not await is_member(db, org_id=agent.org_id, user_id=responder.id):
        raise PermissionDeniedError("Only the provider can respond to this review.")

    if review.response_body is not None:
        raise ConflictError(
            "You have already responded to this review.", code="already_responded"
        )

    review.response_body = body
    review.response_at = datetime.now(UTC)
    await db.flush()
    return review


async def withdraw_review(
    db: AsyncSession, *, review: Review, author: User
) -> Review:
    """Let an author withdraw their review, removing its score contribution."""
    if review.author_id != author.id:
        raise PermissionDeniedError("Only the author can withdraw this review.")

    if review.status != ReviewStatus.PUBLISHED:
        raise ConflictError("This review is not published.", code="not_published")

    review.status = ReviewStatus.WITHDRAWN
    review.withdrawn_at = datetime.now(UTC)

    service = (
        await db.execute(select(Service).where(Service.id == review.service_id))
    ).scalar_one()
    service.review_count = max(0, service.review_count - 1)
    service.rating_sum = max(0, service.rating_sum - review.rating)

    await db.flush()
    await recompute(db, agent_id=review.subject_agent_id)
    return review


async def list_for_agent(
    db: AsyncSession, *, agent_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> tuple[list[Review], int]:
    condition = (
        Review.subject_agent_id == agent_id,
        Review.status == ReviewStatus.PUBLISHED,
    )

    total = (
        await db.execute(select(func.count()).select_from(Review).where(*condition))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Review)
            .where(*condition)
            .order_by(Review.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return list(rows), total


async def reviewable_orders(db: AsyncSession, *, user: User) -> list[Order]:
    """Completed, settled orders this buyer has not yet reviewed."""
    already_reviewed = select(Review.order_id).where(Review.author_id == user.id)

    rows = (
        await db.execute(
            select(Order)
            .join(Escrow, Escrow.order_id == Order.id)
            .where(
                Order.buyer_id == user.id,
                Order.status == OrderStatus.COMPLETED,
                Escrow.status.in_(SETTLED_ESCROW_STATES),
                Order.id.notin_(already_reviewed),
            )
            .order_by(Order.completed_at.desc())
        )
    ).scalars().all()

    return list(rows)
