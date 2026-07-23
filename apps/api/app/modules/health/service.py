"""Dependency health probes.

Every probe performs a real round-trip against the dependency. A probe never
reports healthy because it was unable to run — failures are reported as failures.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

Status = Literal["ok", "degraded", "down"]

# A probe that takes longer than this is reported as degraded rather than ok.
DEGRADED_THRESHOLD_MS = 500.0
PROBE_TIMEOUT_SECONDS = 3.0


@dataclass
class ComponentHealth:
    name: str
    status: Status
    latency_ms: float | None = None
    error: str | None = None
    detail: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status}
        if self.latency_ms is not None:
            payload["latency_ms"] = round(self.latency_ms, 2)
        if self.error:
            payload["error"] = self.error
        if self.detail:
            payload.update(self.detail)
        return payload


def _classify(latency_ms: float) -> Status:
    return "ok" if latency_ms < DEGRADED_THRESHOLD_MS else "degraded"


async def check_database(session: AsyncSession) -> ComponentHealth:
    """Verify the database accepts and answers a trivial query."""
    start = time.perf_counter()
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar_one()
    except Exception as exc:
        logger.warning("health_db_failed", extra={"error_type": type(exc).__name__})
        return ComponentHealth(
            name="database", status="down", error=type(exc).__name__
        )
    latency_ms = (time.perf_counter() - start) * 1000
    return ComponentHealth(
        name="database", status=_classify(latency_ms), latency_ms=latency_ms
    )


async def check_redis() -> ComponentHealth:
    """Verify Redis responds to PING."""
    start = time.perf_counter()
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return ComponentHealth(
            name="redis", status="down", error="redis client not installed"
        )

    client = None
    try:
        client = aioredis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
            socket_timeout=PROBE_TIMEOUT_SECONDS,
        )
        await client.ping()
    except Exception as exc:
        logger.warning("health_redis_failed", extra={"error_type": type(exc).__name__})
        return ComponentHealth(name="redis", status="down", error=type(exc).__name__)
    finally:
        if client is not None:
            # A failure to close the probe connection must not change the health
            # verdict, but it is still worth knowing about, so it is logged.
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug(
                    "health_redis_close_failed",
                    extra={"error_type": type(exc).__name__},
                )

    latency_ms = (time.perf_counter() - start) * 1000
    return ComponentHealth(
        name="redis", status=_classify(latency_ms), latency_ms=latency_ms
    )


def overall_status(components: list[ComponentHealth]) -> Status:
    if any(c.status == "down" for c in components):
        return "down"
    if any(c.status == "degraded" for c in components):
        return "degraded"
    return "ok"
