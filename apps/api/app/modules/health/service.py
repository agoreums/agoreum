"""Dependency health probes.

Every probe performs a real round-trip against the dependency. A probe never
reports healthy because it was unable to run, failures are reported as failures.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

Status = Literal["ok", "degraded", "down"]

# A probe that takes longer than this is reported as degraded rather than ok.
DEGRADED_THRESHOLD_MS = 500.0
PROBE_TIMEOUT_SECONDS = 3.0

# The webhooks delivery worker has no chain cursor to trail, so it records a
# liveness heartbeat in Redis each loop. A heartbeat older than this means the
# loop has stopped draining the outbox even though the container may be up.
WEBHOOK_HEARTBEAT_KEY = "health:worker:webhooks"
WORKER_HEARTBEAT_STALE_SECONDS = 180


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


async def check_chain() -> ComponentHealth:
    """Verify the configured chain is reachable and is the chain we expect.

    Reported as informational rather than as a hard dependency: the platform
    still serves the marketplace, profiles and existing order history when an
    RPC provider is having a bad day. Only funding a new escrow needs the chain,
    and that already fails loudly on its own. Marking the whole service unready
    would take the site down over a third party's outage.
    """
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


async def check_webhooks_worker() -> ComponentHealth:
    """Whether the webhooks delivery loop is still running.

    The worker records a heartbeat timestamp in Redis each loop. A missing
    heartbeat means it has not run yet; a stale one means the loop has stopped
    even if the container is nominally up, so deliveries would silently pile up.
    """
    try:
        from app.core.redis import create_client
    except ImportError:
        return ComponentHealth(
            name="webhooks_worker", status="down", error="redis client not installed"
        )

    client = None
    try:
        client = create_client(timeout=PROBE_TIMEOUT_SECONDS)
        raw = await client.get(WEBHOOK_HEARTBEAT_KEY)
    except Exception as exc:
        logger.warning(
            "health_webhooks_worker_failed", extra={"error_type": type(exc).__name__}
        )
        return ComponentHealth(
            name="webhooks_worker", status="down", error=type(exc).__name__
        )
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug(
                    "health_webhooks_worker_close_failed",
                    extra={"error_type": type(exc).__name__},
                )

    if raw is None:
        return ComponentHealth(
            name="webhooks_worker",
            status="degraded",
            error="no heartbeat recorded yet",
        )

    try:
        last = int(raw)
    except (TypeError, ValueError):
        last = 0
    age = int(time.time()) - last
    status: Status = "ok" if age <= WORKER_HEARTBEAT_STALE_SECONDS else "down"
    return ComponentHealth(
        name="webhooks_worker",
        status=status,
        detail={"heartbeat_age_seconds": str(age)},
    )


def overall_status(components: list[ComponentHealth]) -> Status:
    if any(c.status == "down" for c in components):
        return "down"
    if any(c.status == "degraded" for c in components):
        return "degraded"
    return "ok"
