"""Central model registry.

Importing this module imports every ORM model in the platform, which is what allows
Alembic autogenerate to see the complete schema. Each bounded module owns its own
models; this file only aggregates them so there is exactly one import to keep in sync.
"""
from __future__ import annotations

from app.chain.models import IndexerCursor
from app.db.base import Base
from app.modules.agents.models import (
    Agent,
    AgentDomainChallenge,
    AgentGithubChallenge,
)
from app.modules.apikeys.models import ApiKey
from app.modules.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from app.modules.orders.models import (
    ChainTransaction,
    Escrow,
    Order,
    OrderEvent,
)
from app.modules.reputation.models import ReputationSnapshot, Review
from app.modules.services.models import Category, Service
from app.modules.users.models import Session, SiweNonce, User, Wallet
from app.modules.webhooks.models import WebhookDelivery, WebhookEndpoint

__all__ = [
    "Agent",
    "AgentDomainChallenge",
    "AgentGithubChallenge",
    "ApiKey",
    "Base",
    "Category",
    "ChainTransaction",
    "Escrow",
    "IndexerCursor",
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "Order",
    "OrderEvent",
    "ReputationSnapshot",
    "Review",
    "Service",
    "Session",
    "SiweNonce",
    "User",
    "Wallet",
    "WebhookDelivery",
    "WebhookEndpoint",
]
