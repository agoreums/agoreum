"""Health and readiness endpoints.

- `/health/live`  liveness: is the process up? No dependency calls.
- `/health/ready` readiness: can the process serve traffic? Probes dependencies and
                  returns 503 when any hard dependency is down, so load balancers
                  and container orchestrators can act on it.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.modules.health import service

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
    }


@router.get("/ready", summary="Readiness probe")
async def ready(
    response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    database, redis, chain = await asyncio.gather(
        service.check_database(db),
        service.check_redis(),
        service.check_chain(),
    )

    # Readiness is decided by the dependencies this service cannot serve without.
    # The chain is reported but excluded: an RPC provider outage stops new escrow
    # funding, which already fails loudly on its own, and taking the whole site
    # out of rotation over a third party would be a worse outcome than degrading.
    required = [database, redis]
    overall = service.overall_status(required)

    if overall == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "environment": settings.APP_ENV,
        "components": {
            c.name: c.as_dict() for c in [*required, chain]
        },
        # Stated explicitly so an operator reading this knows which components
        # were actually allowed to fail the check.
        "required_components": [c.name for c in required],
    }


@router.get("/indexer", summary="Indexer freshness")
async def indexer(
    response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    """How far the chain indexer trails the head. 503 when it looks stalled.

    Separate from readiness on purpose: a lagging indexer must not take the site
    out of rotation, but it does need its own signal so monitoring can alert on
    it before buyers notice their paid orders sitting unfunded.
    """
    component = await service.check_indexer(db)
    if component.status == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": component.status, "indexer": component.as_dict()}


@router.get("/workers", summary="Background worker liveness")
async def workers(
    response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    """Liveness of the background workers that have no HTTP surface of their own.

    The subscription indexer is judged by its cursor freshness (like the escrow
    indexer); the delivery loops by the heartbeat each records every pass. 503
    when any has stopped, so the monitor can alert on a stuck worker even though
    its container is up.

    The emails worker was absent here until 2026-08-15. Production ran it and
    nothing watched it, so a wedged loop would have stopped sign-in alerts and
    verification links with no alarm. It is the worker whose silence is hardest
    to notice from outside, because nobody reports mail they never expected.
    """
    sub = await service.check_subscription_indexer(db)
    hook = await service.check_webhooks_worker()
    mail = await service.check_emails_worker()
    overall = service.overall_status([sub, hook, mail])
    if overall == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": overall,
        "subscription_indexer": sub.as_dict(),
        "webhooks_worker": hook.as_dict(),
        "emails_worker": mail.as_dict(),
    }
