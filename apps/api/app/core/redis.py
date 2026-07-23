"""Redis client factory.

One place to construct Redis connections, so caching, rate limiting, and
background job queues all share the same connection settings and compatibility
handling rather than each rediscovering them.
"""
from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

# Two handshake steps in modern redis-py fail against older servers:
#
#   * `HELLO 3` negotiates the RESP3 protocol, which exists only from Redis 6.
#   * `CLIENT SETINFO` reports the client library, and exists only from 7.2.
#
# Both surface as an opaque connection error rather than a clean downgrade. RESP2
# is pinned and the SETINFO handshake disabled, which costs nothing this platform
# uses — caching, rate limiting and job queues are all RESP2-compatible — and
# keeps one client working against every server version we might meet, from a
# developer's local install to DigitalOcean's managed Redis.
_COMPATIBILITY_KWARGS: dict[str, Any] = {
    "protocol": 2,
    "lib_name": None,
    "lib_version": None,
}

DEFAULT_TIMEOUT_SECONDS = 5.0


def create_client(
    *,
    url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    decode_responses: bool = True,
    **kwargs: Any,
) -> aioredis.Redis:
    """Build an async Redis client.

    The caller owns the returned client and is responsible for closing it.
    """
    return aioredis.from_url(
        url or settings.REDIS_URL,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=decode_responses,
        **_COMPATIBILITY_KWARGS,
        **kwargs,
    )
