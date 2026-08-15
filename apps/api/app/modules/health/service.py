"""Dependency health probes.

Every probe performs a real round-trip against the dependency. A probe never
reports healthy because it was unable to run, failures are reported as failures.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

Status = Literal["ok", "degraded", "down"]

# A probe that takes longer than this is reported as degraded rather than ok.
DEGRADED_THRESHOLD_MS = 500.0
PROBE_TIMEOUT_SECONDS = 3.0

# Workers with no chain cursor to trail record a liveness heartbeat in Redis each
# loop. A heartbeat older than this means the loop has stopped even though the
# container may be up.
#
# The emails worker was missing from this list until 2026-08-15, and the shape of
# the omission is worth keeping. The webhooks worker had the pattern, correct and
# load-bearing, one service over. The health endpoint reported two workers and
# looked complete. Production runs four besides the monitor, and the one that had
# no heartbeat is the one that sends sign-in alerts and verification links, so a
# wedged loop would have stopped security mail with nothing raising a hand.
#
# Keyed by name rather than as separate constants so adding a worker means adding
# an entry here, and `check_worker` covers it without new code to forget.
WEBHOOK_HEARTBEAT_KEY = "health:worker:webhooks"
EMAIL_HEARTBEAT_KEY = "health:worker:emails"
WORKER_HEARTBEAT_KEYS = {
    "webhooks_worker": WEBHOOK_HEARTBEAT_KEY,
    "emails_worker": EMAIL_HEARTBEAT_KEY,
}
WORKER_HEARTBEAT_STALE_SECONDS = 180

# The chain probe is the only one on the readiness path that leaves our own
# infrastructure, and it is reported rather than required. Serving it from a
# short-lived cache keeps the reported status honest to within this window while
# stopping an unauthenticated endpoint from turning every request into a billed
# RPC call. The container healthcheck alone asks every 30 seconds; a client can
# ask far faster, and load testing measured the readiness probe capping the API
# at roughly a fifth of the throughput it reaches without it.
CHAIN_CACHE_SECONDS = 15.0


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
        from app.core.redis import create_client
    except ImportError:
        return ComponentHealth(
            name="redis", status="down", error="redis client not installed"
        )

    client = None
    try:
        client = create_client(timeout=PROBE_TIMEOUT_SECONDS)
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


_chain_cache: tuple[float, ComponentHealth] | None = None
_chain_lock: asyncio.Lock | None = None


def _chain_cache_lock() -> asyncio.Lock:
    """The lock, created on first use so it binds to the running loop."""
    global _chain_lock
    if _chain_lock is None:
        _chain_lock = asyncio.Lock()
    return _chain_lock


def reset_chain_cache() -> None:
    """Forget the cached chain probe. For tests, and for a forced re-check."""
    global _chain_cache
    _chain_cache = None


def _cached_chain(now: float) -> ComponentHealth | None:
    if _chain_cache is None:
        return None
    measured_at, health = _chain_cache
    age = now - measured_at
    if age >= CHAIN_CACHE_SECONDS:
        return None
    # The age travels with the answer. A reader deciding whether the chain is
    # genuinely down needs to know the figure may predate their request.
    return replace(health, detail={**health.detail, "age_seconds": str(round(age, 1))})


async def check_chain(*, use_cache: bool = True) -> ComponentHealth:
    """Verify the configured chain is reachable and is the chain we expect.

    Reported as informational rather than as a hard dependency: the platform
    still serves the marketplace, profiles and existing order history when an
    RPC provider is having a bad day. Only funding a new escrow needs the chain,
    and that already fails loudly on its own. Marking the whole service unready
    would take the site down over a third party's outage.

    The result is cached for `CHAIN_CACHE_SECONDS`, and concurrent misses are
    collapsed into a single round-trip, so a burst of readiness checks costs one
    RPC call rather than one each. Failures are cached too: an RPC provider
    having an outage should not also be hammered by our health checks.
    """
    global _chain_cache

    if use_cache:
        cached = _cached_chain(time.monotonic())
        if cached is not None:
            return cached

        async with _chain_cache_lock():
            # Another request may have refreshed it while we waited for the lock.
            cached = _cached_chain(time.monotonic())
            if cached is not None:
                return cached
            health = await _probe_chain()
            _chain_cache = (time.monotonic(), health)
            return health

    health = await _probe_chain()
    _chain_cache = (time.monotonic(), health)
    return health


async def _probe_chain() -> ComponentHealth:
    """One real round-trip to the configured RPC endpoint."""
    from app.chain.client import health_check as chain_health

    start = time.perf_counter()
    try:
        result = await chain_health()
    except Exception as exc:
        logger.warning("health_chain_failed", extra={"error_type": type(exc).__name__})
        return ComponentHealth(name="chain", status="down", error=type(exc).__name__)

    latency_ms = (time.perf_counter() - start) * 1000
    reported = result.get("status")

    if reported == "not_configured":
        return ComponentHealth(
            name="chain",
            status="degraded",
            latency_ms=latency_ms,
            error="no RPC endpoint configured for this network",
        )
    if reported == "wrong_network":
        # Worse than unreachable: the endpoint answers, but for another chain.
        return ComponentHealth(
            name="chain",
            status="down",
            latency_ms=latency_ms,
            error=(
                f"endpoint serves chain {result.get('chain_id')}, "
                f"expected {result.get('expected_chain_id')}"
            ),
        )
    if reported != "ok":
        return ComponentHealth(
            name="chain",
            status="down",
            latency_ms=latency_ms,
            error=str(result.get("error", "unreachable")),
        )

    return ComponentHealth(
        name="chain",
        status=_classify(latency_ms),
        latency_ms=latency_ms,
        detail={
            "network": str(result.get("network", "")),
            "head_block": str(result.get("head_block", "")),
        },
    )


async def check_indexer(session: AsyncSession) -> ComponentHealth:
    """Report how far the indexer's cursor trails the chain head.

    A stalled indexer is invisible to the readiness probe, the API itself is
    perfectly healthy, but it means confirmed on-chain events stop being applied,
    so buyers pay and their orders never move to funded. This makes the gap
    observable so an operator (or the monitor) can be alerted before a user is.
    """
    from sqlalchemy import select

    from app.chain import escrow as contract
    from app.chain.client import ChainClient
    from app.chain.models import IndexerCursor
    from app.core.config import settings

    if not contract.is_configured():
        return ComponentHealth(
            name="indexer", status="degraded", error="no escrow contract configured"
        )

    try:
        address = contract.contract_address()
        cursor = (
            await session.execute(
                select(IndexerCursor).where(
                    IndexerCursor.chain_id == settings.CHAIN_ID,
                    IndexerCursor.contract_address == address,
                )
            )
        ).scalar_one_or_none()
        async with ChainClient() as client:
            head = await client.block_number()
    except Exception as exc:
        logger.warning("health_indexer_failed", extra={"error_type": type(exc).__name__})
        return ComponentHealth(name="indexer", status="down", error=type(exc).__name__)

    if cursor is None:
        # No cursor: the indexer has not completed a scan for this contract yet.
        return ComponentHealth(
            name="indexer",
            status="degraded",
            error="indexer has not recorded a scan yet",
            detail={"head_block": str(head)},
        )

    lag = head - cursor.last_scanned_block
    # Normal lag is the confirmation depth plus a poll interval of blocks, a
    # handful on Base's ~2s blocks. Generous slack before calling it stalled.
    status: Status = "ok" if lag <= 40 else "degraded" if lag <= 200 else "down"
    return ComponentHealth(
        name="indexer",
        status=status,
        detail={
            "head_block": str(head),
            "last_scanned_block": str(cursor.last_scanned_block),
            "lag_blocks": str(lag),
        },
    )


async def check_subscription_indexer(session: AsyncSession) -> ComponentHealth:
    """How far the subscription indexer trails the head.

    The mirror of `check_indexer` for the subscription contract's own cursor. A
    stalled subscription indexer means confirmed payments stop activating
    subscriptions, so a subscriber pays and their access never turns on.
    """
    from sqlalchemy import select

    from app.chain import subscriptions as contract
    from app.chain.client import ChainClient
    from app.chain.models import IndexerCursor
    from app.core.config import settings

    if not contract.is_configured():
        return ComponentHealth(
            name="subscription_indexer",
            status="degraded",
            error="no subscription contract configured",
        )

    try:
        address = contract.contract_address()
        cursor = (
            await session.execute(
                select(IndexerCursor).where(
                    IndexerCursor.chain_id == settings.CHAIN_ID,
                    IndexerCursor.contract_address == address.lower(),
                )
            )
        ).scalar_one_or_none()
        async with ChainClient() as client:
            head = await client.block_number()
    except Exception as exc:
        logger.warning(
            "health_subscription_indexer_failed", extra={"error_type": type(exc).__name__}
        )
        return ComponentHealth(
            name="subscription_indexer", status="down", error=type(exc).__name__
        )

    if cursor is None:
        return ComponentHealth(
            name="subscription_indexer",
            status="degraded",
            error="subscription indexer has not recorded a scan yet",
            detail={"head_block": str(head)},
        )

    lag = head - cursor.last_scanned_block
    status: Status = "ok" if lag <= 40 else "degraded" if lag <= 200 else "down"
    return ComponentHealth(
        name="subscription_indexer",
        status=status,
        detail={
            "head_block": str(head),
            "last_scanned_block": str(cursor.last_scanned_block),
            "lag_blocks": str(lag),
        },
    )


async def check_worker(name: str) -> ComponentHealth:
    """Whether a heartbeat-reporting worker loop is still running.

    The worker records a timestamp in Redis each pass. A missing heartbeat means
    it has not run yet; a stale one means the loop has stopped even if the
    container is nominally up, so its queue would silently pile up.
    """
    key = WORKER_HEARTBEAT_KEYS.get(name)
    if key is None:  # a wiring mistake, not a runtime condition
        return ComponentHealth(name=name, status="down", error="no heartbeat key configured")

    try:
        from app.core.redis import create_client
    except ImportError:
        return ComponentHealth(name=name, status="down", error="redis client not installed")

    client = None
    try:
        client = create_client(timeout=PROBE_TIMEOUT_SECONDS)
        raw = await client.get(key)
    except Exception as exc:
        logger.warning(
            "health_worker_probe_failed",
            extra={"worker": name, "error_type": type(exc).__name__},
        )
        return ComponentHealth(name=name, status="down", error=type(exc).__name__)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug(
                    "health_worker_close_failed",
                    extra={"worker": name, "error_type": type(exc).__name__},
                )

    if raw is None:
        return ComponentHealth(name=name, status="degraded", error="no heartbeat recorded yet")

    try:
        last = int(raw)
    except (TypeError, ValueError):
        last = 0
    age = int(time.time()) - last
    status: Status = "ok" if age <= WORKER_HEARTBEAT_STALE_SECONDS else "down"
    return ComponentHealth(name=name, status=status, detail={"heartbeat_age_seconds": str(age)})


async def check_webhooks_worker() -> ComponentHealth:
    """Kept as a named entry point; the logic now lives in `check_worker`."""
    return await check_worker("webhooks_worker")


async def check_emails_worker() -> ComponentHealth:
    return await check_worker("emails_worker")


def overall_status(components: list[ComponentHealth]) -> Status:
    if any(c.status == "down" for c in components):
        return "down"
    if any(c.status == "degraded" for c in components):
        return "degraded"
    return "ok"
