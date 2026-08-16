"""Aggregation point for all v1 API routes.

Each bounded module exposes a router here. Keeping registration in one place makes
the platform's public surface reviewable at a glance and keeps module boundaries
explicit, which is what allows a module to be extracted into its own service later.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.admin.router import router as admin_router
from app.modules.agents.router import router as agents_router
from app.modules.analytics.router import router as analytics_router
from app.modules.apikeys.router import router as apikeys_router
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.health.router import router as health_router
from app.modules.identity.router import router as identity_router
from app.modules.marketplace.router import router as marketplace_router
from app.modules.mcp.router import router as mcp_router
from app.modules.notifications.router import router as notifications_router
from app.modules.orders.router import router as orders_router
from app.modules.organizations.router import router as organizations_router
from app.modules.receipts.router import router as receipts_router
from app.modules.reputation.router import router as reputation_router
from app.modules.services.router import router as services_router
from app.modules.subscriptions.router import router as subscriptions_router
from app.modules.webhooks.router import router as webhooks_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(marketplace_router)
api_router.include_router(mcp_router)
api_router.include_router(receipts_router)
api_router.include_router(services_router)
api_router.include_router(orders_router)
api_router.include_router(reputation_router)
api_router.include_router(notifications_router)
api_router.include_router(dashboard_router)
api_router.include_router(analytics_router)
api_router.include_router(admin_router)
api_router.include_router(organizations_router)
api_router.include_router(apikeys_router)
api_router.include_router(identity_router)
api_router.include_router(webhooks_router)
api_router.include_router(subscriptions_router)


