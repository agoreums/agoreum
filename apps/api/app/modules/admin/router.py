"""Operational endpoints.

Every route here is gated on an address the chain recognises, and every gate
fails closed when that address is unconfigured. Nothing here moves money: the
dispute queue is a list, and the settlement itself is still sent by the arbiter's
own wallet through the orders API.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import PermissionDeniedError
from app.modules.admin import service
from app.modules.admin.schemas import (
    DisputeQueueItem,
    ReputationExclusionRequest,
    ReputationExclusionView,
    ReputationRecomputeView,
    SuppressionView,
)
from app.modules.notifications import service as notifications
from app.modules.orders import service as orders

router = APIRouter(prefix="/admin", tags=["administration"])


def _require_admin(user: CurrentUser) -> None:
    if not service.is_platform_admin(user):
        raise PermissionDeniedError(
            "This account cannot administer the platform.", code="not_admin"
        )


@router.get(
    "/disputes",
    response_model=list[DisputeQueueItem],
    summary="Disputes waiting for a decision",
)
async def dispute_queue(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DisputeQueueItem]:
    """Open to the arbiter, since it is the arbiter's work queue.

    An administrator who is not the arbiter cannot decide anything, so showing
    them the queue would only invite them to try.
    """
    if not orders.is_arbiter(user):
        raise PermissionDeniedError(
            "Only the arbiter can see the dispute queue.", code="not_arbiter"
        )
    rows = await service.open_disputes(db, limit=limit)
    return [DisputeQueueItem(**row) for row in rows]


@router.get(
    "/email-suppressions",
    response_model=list[SuppressionView],
    summary="Addresses the platform will not mail",
)
async def suppressions(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SuppressionView]:
    _require_admin(user)
    return [SuppressionView(**row) for row in await service.list_suppressions(db, limit=limit)]


@router.delete(
    "/email-suppressions/{email}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lift a suppression",
)
async def lift_suppression(email: str, user: CurrentUser, db: DbSession) -> None:
    """Deliberately a human action.

    An address comes off this list because somebody decided it should, not
    because time passed: a mailbox that hard bounced yesterday is still gone
    today, and a complaint does not expire. Until now there was no way to make
    that decision at all, which made every suppression permanent by accident
    rather than by choice.
    """
    _require_admin(user)
    await notifications.unsuppress_email(db, email=email)


@router.post(
    "/orders/{order_id}/exclude-from-reputation",
    response_model=ReputationExclusionView,
    summary="Stop a settled order counting toward its provider's standing",
)
async def exclude_from_reputation(
    order_id: uuid.UUID,
    payload: ReputationExclusionRequest,
    user: CurrentUser,
    db: DbSession,
) -> ReputationExclusionView:
    """For a real settlement that must not become standing.

    The case this exists for is one the platform cannot detect for itself. An
    order between two accounts sharing no organization, no wallet and nothing
    else visible is indistinguishable from arm's length trade, however well the
    operator knows otherwise. The first instance was the settlement exercise of
    2026-08-16, which proved the receipt path against production and left behind
    exactly such an order.

    **There is deliberately no route that lifts one.** The absence is not an
    oversight to be filled in later, and filling it in would not work: a database
    trigger refuses to clear an exclusion, to rewrite its timestamp, or to
    rewrite its reason. A reversible flag is a way of handing out standing, so
    the only safe version of this power is one that can only ever subtract.

    Nothing about the order changes. The payment happened, the escrow settled,
    and the receipt still points at a transaction anybody can follow on chain.
    """
    _require_admin(user)
    order = await service.exclude_order_from_reputation(
        db, order_id=order_id, actor=user, reason=payload.reason
    )
    return ReputationExclusionView(
        order_id=order.id,
        order_reference=order.reference,
        provider_agent_id=order.provider_agent_id,
        reputation_excluded_at=order.reputation_excluded_at,
        reputation_exclusion_reason=order.reputation_exclusion_reason,
    )


@router.post(
    "/agents/{slug}/recompute-reputation",
    response_model=ReputationRecomputeView,
    summary="Rebuild an agent's published reputation from its underlying rows",
)
async def recompute_reputation(
    slug: str, user: CurrentUser, db: DbSession
) -> ReputationRecomputeView:
    """A repair tool for a published number that has stopped following the data.

    The public reputation is a stored snapshot, refreshed by events: a settled
    order, a review, an exclusion. Anything that goes wrong outside those paths
    strands a figure that no longer follows from the rows behind it, and there
    was no way to correct one without writing to the database directly.

    It cannot manufacture standing. Every figure is derived from orders and
    reviews, and there is no argument here or in `recompute` that could carry a
    score, so the only reachable outcome is the published number matching the
    data.
    """
    _require_admin(user)
    agent, snapshot = await service.recompute_agent_reputation(
        db, slug=slug, actor=user
    )
    return ReputationRecomputeView(
        agent_slug=agent.slug,
        computed_at=snapshot.computed_at,
        completed_orders=snapshot.completed_orders,
        total_volume=snapshot.total_volume,
        score=snapshot.score,
    )


@router.post(
    "/orders/{order_id}/repair-from-chain",
    summary="Make an order's recorded amounts match the chain",
)
async def repair_from_chain(
    order_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> dict:
    """Closes a divergence that `reconcile` can only report.

    The chain is authoritative here, which the reconciliation already says, so
    this copies its figures into the database and writes nothing that did not
    come from the contract in the same call. There is no argument that could
    carry a number, so the only reachable outcome is the database agreeing with
    the chain.

    Needed because a detector without a repair leaves an operator reading a true
    report they cannot act on. The first settled dispute recorded the provider's
    net where the chain holds the gross, and fixing the indexer did nothing for
    the row already written, since events are processed once.

    Status is not rewritten. Amounts are facts the contract holds; status is a
    projection this application derives, with order state, notifications and
    reputation hanging off it.
    """
    _require_admin(user)
    return await service.repair_order_from_chain(db, order_id=order_id, actor=user)
