"""Central model registry.

Importing this module imports every ORM model in the platform, which is what allows
Alembic autogenerate to see the complete schema. Each bounded module owns its own
models; this file only aggregates them so there is exactly one import to keep in sync.
"""
from __future__ import annotations

from app.db.base import Base  # noqa: F401

# Module models are registered here as each stage lands.
# Stage 3 populates: users, wallets, agents, services, transactions,
# reputation, notifications.

__all__ = ["Base"]
