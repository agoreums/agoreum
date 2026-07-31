"""Dashboard endpoints.

Every figure is counted from real rows. A new account sees zeros because it has
done nothing yet, and figures that cannot be known are null rather than zero.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.modules.dashboard import service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/buyer", summary="Your buying activity")
async def buyer(user: CurrentUser, db: DbSession) -> dict:
    return asdict(await service.buyer_dashboard(db, user=user))


@router.get("/provider", summary="Your agents' activity")
async def provider(user: CurrentUser, db: DbSession) -> dict:
    """Returns zeros and nulls for an account with no agents, rather than
    hiding the section, the absence is itself the useful information."""
    return asdict(await service.provider_dashboard(db, user=user))


@router.get("/admin", summary="Platform-wide totals")
async def admin(_: AdminUser, db: DbSession) -> dict:
    return asdict(await service.admin_dashboard(db))
