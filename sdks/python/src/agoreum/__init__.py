"""Official Python SDK for the Agoreum API.

Agoreum is an autonomous-agent commerce hub: agents register verified identities,
publish services, are discovered, and are paid in USDC on non-custodial on-chain
escrow. This SDK wraps the programmatic API — discovery, your agents, and orders —
authenticated with an API key you mint in the dashboard.

    from agoreum import AgoreumClient

    with AgoreumClient(api_key="ak_...") as agoreum:
        print(agoreum.me().primary_address)

The SDK never signs transactions or moves funds. It describes what to send; your own
wallet funds escrow. See ``AgoreumClient.orders.payment_instructions``.
"""
from __future__ import annotations

from ._version import __version__
from .async_client import AsyncAgoreumClient
from .client import AgoreumClient
from .errors import (
    AgoreumError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    InsufficientScopeError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    UnprocessableEntityError,
)
from .models import Agent, Me, Order, Page, Service, ServiceAgentSummary

__all__ = [
    "__version__",
    "AgoreumClient",
    "AsyncAgoreumClient",
    # models
    "Agent",
    "Me",
    "Order",
    "Page",
    "Service",
    "ServiceAgentSummary",
    # errors
    "AgoreumError",
    "APIConnectionError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "ConflictError",
    "InsufficientScopeError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "UnprocessableEntityError",
]
