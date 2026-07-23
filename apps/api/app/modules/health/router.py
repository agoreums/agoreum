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
