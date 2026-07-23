"""Aggregation point for all v1 API routes.

Each bounded module exposes a router here. Keeping registration in one place makes
the platform's public surface reviewable at a glance and keeps module boundaries
explicit, which is what allows a module to be extracted into its own service later.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.health.router import router as health_router

api_router = APIRouter()

api_router.include_router(health_router)

# Modules registered in later stages: auth, users, agents, services, marketplace,
# transactions, payments, wallets, reputation, notifications, analytics, admin.
