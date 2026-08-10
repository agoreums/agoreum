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

import ipaddress
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
    # Tighter than the others, because this one causes mail to be sent to an
    # address the caller chose. Loose limits here would make the platform a way to
    # repeatedly mail somebody, using this domain's sending reputation to do it.
    #
    # Two buckets rather than one, because a single window cannot serve both
    # cases. The burst window stops rapid-fire sending to a victim; the daily one
    # stops a patient attacker trickling messages all day. A single "three an
    # hour" did neither well: it locked out a real person for a full hour after
    # three attempts, which is exactly what somebody does when the first message
    # does not arrive, while still permitting seventy-two sends a day.
    "auth:verify-email": Limit(requests=3, window_seconds=900),
    "auth:verify-email:daily": Limit(requests=10, window_seconds=86_400),
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


def rate_limit_scope(ip: str) -> str:
    """The smallest unit of address a caller cannot trivially change.

    An IPv4 address is that unit. An IPv6 one is not: a residential allocation
    is typically a /64, which is eighteen quintillion addresses the same client
    may source from at will. Counting per /128 therefore imposes no limit at all
    on anyone using IPv6, including on `auth:verify-email`, whose whole stated
    purpose is to stop rapid-fire mail to a victim.

    Collapsed to the /64 so the quota applies to the party, not the address.
    Anything unparseable is returned unchanged rather than guessed at.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip

    if address.version == 6:
        mapped = address.ipv4_mapped
        if mapped is not None:
            return str(mapped)
        return f"{ipaddress.IPv6Network((address, 64), strict=False).network_address}/64"
    return str(address)


def client_identity(request: Request) -> str:
    """Who to count against.

    An authenticated caller is counted by user id, so one abusive account cannot
    exhaust the quota of everyone sharing an IP, a real problem behind corporate
    NAT or a mobile carrier, and so rotating addresses does not reset a quota.
    Anonymous callers fall back to the client IP as resolved by `client_ip`,
    which trusts only Cloudflare's header.

    The account is read from `request.state.user_id` when something has already
    resolved it, and otherwise from the bearer token directly. That second path
    is not redundant. Limiters are declared as route-level dependencies, and
    FastAPI resolves those before the path function's own parameters, so the
    limiter runs before `get_current_user` has set anything. Relying on the
    state alone meant every authenticated route silently used the IP bucket,
    which is the opposite of what this function documents.

    Decoding is signature-verified and costs no database round trip: only the
    subject is needed, not the account. An expired or forged token resolves to
    nobody and falls through to the address, which is correct, since such a
    caller is not authenticated.
    """
    from app.api.deps import client_ip

    user = getattr(request.state, "user_id", None)
    if not user:
        user = _subject_from_bearer(request)
    if user:
        return f"user:{user}"

    return f"ip:{rate_limit_scope(client_ip(request) or 'unknown')}"


def _subject_from_bearer(request: Request) -> str | None:
    """The account a valid bearer token belongs to, or None."""
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    from app.core.security import decode_access_token

    try:
        return decode_access_token(token.strip()).get("sub")
    except Exception:
        # Any invalid token counts as anonymous. Refusing the request is the
        # authentication layer's job, and doing it here would turn a stale
        # browser token into a failure on endpoints that allow anonymous use.
        return None


def retry_phrase(seconds: int) -> str:
    """How long to wait, in words.

    Said plainly rather than as "a moment". A refusal that hides the wait invites
    the person to keep retrying, which is futile and is the behaviour the limit
    exists to discourage in the first place.
    """
    if seconds >= 90:
        return f"in about {round(seconds / 60)} minutes"
    if seconds > 1:
        return f"in {seconds} seconds"
    return "shortly"


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
            f"Too many requests. Try again {retry_phrase(decision.reset_after)}.",
            details={"retry_after_seconds": decision.reset_after},
        )


def limiter(bucket: str):
    """Build a FastAPI dependency enforcing a named bucket."""

    async def dependency(request: Request) -> None:
        await enforce(request, bucket)

    return dependency
