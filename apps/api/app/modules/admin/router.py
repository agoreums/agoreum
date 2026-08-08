"""Operational endpoints.

Every route here is gated on an address the chain recognises, and every gate
fails closed when that address is unconfigured. Nothing here moves money: the
dispute queue is a list, and the settlement itself is still sent by the arbiter's
own wallet through the orders API.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import PermissionDeniedError
from app.modules.admin import service
from app.modules.admin.schemas import DisputeQueueItem, SuppressionView
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
