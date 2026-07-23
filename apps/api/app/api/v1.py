"""Aggregation point for all v1 API routes.

Each bounded module exposes a router here. Keeping registration in one place makes
the platform's public surface reviewable at a glance and keeps module boundaries
explicit, which is what allows a module to be extracted into its own service later.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)

# Modules registered in later stages: users, agents, services, marketplace,
# transactions, payments, reputation, notifications, analytics, admin.
