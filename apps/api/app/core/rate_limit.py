"""Rate limiting.

Counters live in Redis rather than in process memory, because the platform runs
behind a load balancer: an in-memory limiter would give an attacker one full
allowance per replica, and would reset every deploy.

The algorithm is a fixed window implemented as `INCR` plus `EXPIRE` in a single
pipeline. A sliding window is more precise at the boundary, but a fixed window
is one round trip, has no unbounded memory growth, and the boundary imprecision
(briefly allowing up to twice the limit across two adjacent windows) does not
matter for the abuse this is defending against.

**Failure policy is fail-open, deliberately.** If Redis is unreachable, requests
are allowed and the failure is logged loudly. Failing closed would turn a cache
outage into a total outage, nobody could sign in, and no provider could be
paid. Rate limiting is a shield against abuse, not the thing preventing
unauthorised access: that is the signature check, which is unaffected. The
tradeoff is stated here so it is a decision rather than an accident.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings
from app.core.errors import RateLimitError
from app.core.logging import get_logger
from app.core.redis import create_client

logger = get_logger(__name__)

KEY_PREFIX = "ratelimit"


@dataclass(frozen=True)
class Limit:
    """A quota: `requests` allowed per `window_seconds`."""

    requests: int
    window_seconds: int

    @property
    def label(self) -> str:
        return f"{self.requests}/{self.window_seconds}s"


# Endpoint quotas. Anything that is expensive, or that an attacker would want to
# repeat, gets a tighter limit than the global default.
LIMITS: dict[str, Limit] = {
    # Cheap to request but each one costs a database row, and they are the
    # first step of any sign-in attempt.
    "auth:nonce": Limit(requests=20, window_seconds=60),
    # Signature verification is comparatively expensive, and this is the
    # endpoint an attacker would hammer.
    "auth:signin": Limit(requests=10, window_seconds=60),
    "auth:refresh": Limit(requests=30, window_seconds=60),
    # Deliberately far tighter than the others, because this one causes mail to
    # be sent to an address the caller chose. Loose limits here would make the
    # platform a way to repeatedly mail somebody, using this domain's sending
    # reputation to do it. Three an hour is ample for a real person who mistyped
    # their address or lost the first message.
    "auth:verify-email": Limit(requests=3, window_seconds=3600),
    # Writes that create durable records.
    "agents:create": Limit(requests=5, window_seconds=300),
    "services:create": Limit(requests=20, window_seconds=300),
    "orders:create": Limit(requests=20, window_seconds=300),
    "reviews:create": Limit(requests=10, window_seconds=300),
    # Domain verification performs an outbound DNS lookup or HTTPS fetch, so it
    # is both expensive and a potential amplification vector.
    "agents:verify_domain": Limit(requests=10, window_seconds=300),
    "agents:verify_github": Limit(requests=10, window_seconds=300),
    # Search hits the database with a full-text query.
    "marketplace:search": Limit(requests=120, window_seconds=60),
    # An unauthenticated endpoint a provider posts to. Deliberately generous:
    # every event arrives from a small set of provider addresses, so they all
    # share one bucket, and refusing a genuine bounce report is worse than
    # absorbing a forged one, which costs a single HMAC to reject. Turning
    # somebody away is recoverable either way, since a non-2xx makes Svix retry.
    "notifications:resend_webhook": Limit(requests=600, window_seconds=60),
}


def default_limit() -> Limit:
    return Limit(requests=settings.RATE_LIMIT_PER_MINUTE, window_seconds=60)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_after: int
    # True when Redis could not be consulted, so the request was let through
    # without being counted.
    degraded: bool = False


async def check(
    *, bucket: str, identity: str, limit: Limit | None = None
) -> Decision:
    """Consume one unit from a bucket and report whether the caller may proceed."""
    quota = limit or LIMITS.get(bucket) or default_limit()

    if not settings.RATE_LIMIT_ENABLED:
        return Decision(
            allowed=True,
            limit=quota.requests,
            remaining=quota.requests,
            reset_after=quota.window_seconds,
        )

    window = quota.window_seconds
    now = int(time.time())
    window_start = now - (now % window)
    key = f"{KEY_PREFIX}:{bucket}:{identity}:{window_start}"

    client = None
    try:
        client = create_client()
        pipeline = client.pipeline()
        pipeline.incr(key)
        # Expiry is set on every call rather than only on creation: a key that
        # somehow lost its TTL would otherwise block a caller permanently.
        pipeline.expire(key, window + 1)
        count, _ = await pipeline.execute()
    except Exception as exc:
        logger.warning(
            "rate_limit_unavailable",
            extra={"bucket": bucket, "error_type": type(exc).__name__},
        )
        return Decision(
            allowed=True,
            limit=quota.requests,
            remaining=quota.requests,
            reset_after=window,
            degraded=True,
        )
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.debug("rate_limit_client_close_failed")

    reset_after = window_start + window - now
    remaining = max(0, quota.requests - int(count))
    allowed = int(count) <= quota.requests

    if not allowed:
        logger.info(
            "rate_limit_exceeded",
            extra={"bucket": bucket, "limit": quota.label},
        )

    return Decision(
        allowed=allowed,
        limit=quota.requests,
        remaining=remaining,
        reset_after=reset_after,
    )


def client_identity(request: Request) -> str:
    """Who to count against.

    An authenticated caller is counted by user id, so one abusive account cannot
    exhaust the quota of everyone sharing an IP, a real problem behind
    corporate NAT or a mobile carrier. Anonymous callers fall back to the
    client IP as resolved by `client_ip`, which trusts only Cloudflare's header.
    """
    from app.api.deps import client_ip

    user = getattr(request.state, "user_id", None)
    if user:
        return f"user:{user}"

    return f"ip:{client_ip(request) or 'unknown'}"


async def enforce(request: Request, bucket: str) -> None:
    """Apply a limit, raising if the caller has exhausted it.

    Used as a dependency on the routes that need protecting.
    """
    decision = await check(bucket=bucket, identity=client_identity(request))

    # Surfaced on every response so a well-behaved client can back off before
    # being refused, rather than discovering the limit by hitting it.
    request.state.rate_limit = decision

    if not decision.allowed:
        raise RateLimitError(
            "Too many requests. Please wait a moment and try again.",
            details={"retry_after_seconds": decision.reset_after},
        )


def limiter(bucket: str):
    """Build a FastAPI dependency enforcing a named bucket."""

    async def dependency(request: Request) -> None:
        await enforce(request, bucket)

    return dependency
