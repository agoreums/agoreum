"""Aggregation point for all v1 API routes.

Each bounded module exposes a router here. Keeping registration in one place makes
the platform's public surface reviewable at a glance and keeps module boundaries
explicit, which is what allows a module to be extracted into its own service later.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.marketplace.router import router as marketplace_router
from app.modules.services.router import router as services_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(marketplace_router)
api_router.include_router(services_router)

# Modules registered in later stages: orders, payments,
# reputation, notifications, analytics, admin.
