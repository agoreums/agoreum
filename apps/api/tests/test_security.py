"""Rate limiting and request-hardening tests.

The rate limiter is disabled in the local environment so the suite does not
throttle its own hundreds of sign-ins. These tests turn it back on explicitly
and flush their own counters, so the behaviour is genuinely exercised against
real Redis rather than assumed.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import rate_limit
from app.core.config import settings
from app.core.redis import create_client
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        # Generous on purpose. The earlier value was 5 seconds, to "fail fast
        # when nothing is listening", but that is not what makes it fast:
        # a closed port on loopback refuses the connection in about two
        # seconds whatever the timeout, measured both ways. The timeout only
        # bites when a database *is* listening and slow, which on a loaded
        # machine turned into an error in one full run and a silently skipped
        # test in the next. A skipped test is the failure this project treats
        # as serious, so the setting that caused it is the one that was wrong.
        connect_args={"timeout": 30},
    )
    try:
        async with eng.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        await eng.dispose()
        pytest.skip(f"no database reachable: {type(exc).__name__}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def redis_available() -> bool:
    try:
        c = create_client()
        await c.ping()
        await c.aclose()
        return True
    except Exception:  # pragma: no cover - environment dependent
        pytest.skip("Redis not reachable")


@pytest_asyncio.fixture
async def limiting_on(monkeypatch, redis_available):
    """Enable rate limiting and clear this test's counters."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    client = create_client()
    keys = [k async for k in client.scan_iter(f"{rate_limit.KEY_PREFIX}:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()

    yield

    client = create_client()
    keys = [k async for k in client.scan_iter(f"{rate_limit.KEY_PREFIX}:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


class TestRateLimiter:
    async def test_allows_traffic_below_the_quota(self, limiting_on) -> None:
        identity = f"test:{uuid.uuid4()}"
        limit = rate_limit.Limit(requests=5, window_seconds=60)

        for _ in range(5):
            decision = await rate_limit.check(
                bucket="unit-test", identity=identity, limit=limit
            )
            assert decision.allowed

    async def test_refuses_once_the_quota_is_spent(self, limiting_on) -> None:
        identity = f"test:{uuid.uuid4()}"
        limit = rate_limit.Limit(requests=3, window_seconds=60)

        for _ in range(3):
            assert (
                await rate_limit.check(
                    bucket="unit-test", identity=identity, limit=limit
                )
            ).allowed

        refused = await rate_limit.check(
            bucket="unit-test", identity=identity, limit=limit
        )
        assert refused.allowed is False
        assert refused.remaining == 0
        assert refused.reset_after > 0

    async def test_counters_are_isolated_per_identity(self, limiting_on) -> None:
        """One abusive caller must not exhaust everyone else's allowance."""
        limit = rate_limit.Limit(requests=2, window_seconds=60)
        noisy = f"test:{uuid.uuid4()}"
        quiet = f"test:{uuid.uuid4()}"

        for _ in range(3):
            await rate_limit.check(bucket="unit-test", identity=noisy, limit=limit)

        assert (
            await rate_limit.check(bucket="unit-test", identity=noisy, limit=limit)
        ).allowed is False
        assert (
            await rate_limit.check(bucket="unit-test", identity=quiet, limit=limit)
        ).allowed is True

    async def test_counters_are_isolated_per_bucket(self, limiting_on) -> None:
        """Exhausting sign-in attempts must not also block searching."""
        identity = f"test:{uuid.uuid4()}"
        limit = rate_limit.Limit(requests=1, window_seconds=60)

        await rate_limit.check(bucket="bucket-a", identity=identity, limit=limit)
        assert (
            await rate_limit.check(bucket="bucket-a", identity=identity, limit=limit)
        ).allowed is False
        assert (
            await rate_limit.check(bucket="bucket-b", identity=identity, limit=limit)
        ).allowed is True

    async def test_disabled_limiter_never_refuses(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
        identity = f"test:{uuid.uuid4()}"
        limit = rate_limit.Limit(requests=1, window_seconds=60)

        for _ in range(10):
            assert (
                await rate_limit.check(
                    bucket="unit-test", identity=identity, limit=limit
                )
            ).allowed

    async def test_fails_open_when_redis_is_unreachable(self, monkeypatch) -> None:
        """A cache outage must not become a total outage.

        Failing closed would stop every sign-in and every settlement. The
        signature check is what actually prevents unauthorised access, and it is
        unaffected by Redis being down.
        """
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

        def _broken(*args, **kwargs):
            raise ConnectionError("redis is down")

        monkeypatch.setattr(rate_limit, "create_client", _broken)

        decision = await rate_limit.check(bucket="unit-test", identity="anyone")

        assert decision.allowed is True
        assert decision.degraded is True


class TestRateLimitedEndpoints:
    async def test_signin_endpoint_refuses_after_its_quota(
        self, client: AsyncClient, limiting_on
    ) -> None:
        """Exercised end to end, so the dependency is genuinely wired up."""
        quota = rate_limit.LIMITS["auth:signin"].requests

        statuses = []
        for _ in range(quota + 2):
            response = await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": "not a real message",
                    "signature": "0x00",
                    "nonce": "irrelevant",
                },
            )
            statuses.append(response.status_code)

        assert 429 in statuses, f"never rate limited: {statuses}"

    async def test_refusal_says_how_long_to_wait(
        self, client: AsyncClient, limiting_on
    ) -> None:
        quota = rate_limit.LIMITS["auth:signin"].requests

        last = None
        for _ in range(quota + 3):
            last = await client.post(
                "/api/v1/auth/signin",
                json={"message": "x", "signature": "0x00", "nonce": "y"},
            )
            if last.status_code == 429:
                break

        assert last is not None and last.status_code == 429
        body = last.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["details"]["retry_after_seconds"] > 0
        assert last.headers.get("Retry-After")

    async def test_remaining_quota_is_published_on_success(
        self, client: AsyncClient, limiting_on
    ) -> None:
        """A client that can see its allowance can back off before being refused."""
        response = await client.post("/api/v1/auth/nonce", json={})

        assert response.status_code == 201
        assert response.headers.get("X-RateLimit-Limit")
        assert response.headers.get("X-RateLimit-Remaining")
        assert response.headers.get("X-RateLimit-Reset")


class TestRequestHardening:
    async def test_oversized_body_is_refused_before_parsing(
        self, client: AsyncClient
    ) -> None:
        """A declared multi-gigabyte body must not reach a validator."""
        response = await client.post(
            "/api/v1/auth/nonce",
            content=b"{}",
            headers={
                "Content-Length": str(50 * 1024 * 1024),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"

    async def test_malformed_content_length_is_refused(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/auth/nonce",
            content=b"{}",
            headers={"Content-Length": "not-a-number", "Content-Type": "application/json"},
        )
        assert response.status_code in {400, 422}

    async def test_normal_body_passes_through(self, client: AsyncClient) -> None:
        assert (
            await client.post("/api/v1/auth/nonce", json={})
        ).status_code == 201

    @pytest.mark.parametrize(
        "header",
        [
            "content-security-policy",
            "x-content-type-options",
            "x-frame-options",
            "referrer-policy",
            "permissions-policy",
            "cross-origin-opener-policy",
        ],
    )
    async def test_security_headers_on_every_response(
        self, client: AsyncClient, header: str
    ) -> None:
        response = await client.get("/api/v1/health/live")
        assert header in {k.lower() for k in response.headers}

    async def test_server_does_not_advertise_its_stack(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/health/live")
        assert "x-powered-by" not in {k.lower() for k in response.headers}

    async def test_request_id_is_returned_for_correlation(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/health/live")
        assert response.headers.get("X-Request-ID")


class TestErrorDisclosure:
    async def test_errors_use_one_envelope(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/orders/not-a-uuid")
        assert response.status_code in {401, 422}
        assert "error" in response.json()

    async def test_unauthenticated_error_reveals_nothing_extra(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/orders")).json()

        assert body["error"]["code"] == "unauthenticated"
        # No stack trace, no SQL, no internal paths.
        serialised = str(body).lower()
        for leak in ("traceback", "select ", "sqlalchemy", "postgres", "/app/"):
            assert leak not in serialised


class TestVerificationEmailLimits:
    """The quota on a flow that mails an address the caller chose.

    Both directions matter. Too loose and the platform becomes a way to
    repeatedly mail a stranger using this domain's reputation. Too tight and a
    real person whose first message did not arrive is locked out for an hour,
    which is what happened.
    """

    def test_a_burst_recovers_in_minutes_not_an_hour(self) -> None:
        burst = rate_limit.LIMITS["auth:verify-email"]
        assert burst.window_seconds <= 900, "a lockout longer than this punishes a retry"
        assert burst.requests >= 3, "one retry after a missing message must be allowed"

    def test_sustained_sending_is_capped_per_day(self) -> None:
        """The burst window alone would still permit dozens of messages a day."""
        daily = rate_limit.LIMITS["auth:verify-email:daily"]
        burst = rate_limit.LIMITS["auth:verify-email"]
        per_day_from_burst = burst.requests * (86_400 / burst.window_seconds)
        assert daily.requests < per_day_from_burst, (
            "the daily cap has to bind, or it is decoration"
        )
        assert daily.window_seconds == 86_400

    def test_both_buckets_guard_the_endpoint(self) -> None:
        """A bucket that exists but is not applied protects nothing."""
        from app.modules.auth import router as auth_router

        route = next(
            r for r in auth_router.router.routes
            if getattr(r, "path", "").endswith("/me/email/verify")
        )
        assert len(route.dependencies) >= 2

    def test_a_refusal_says_how_long_to_wait(self) -> None:
        """"Please wait a moment" for a fifteen minute lockout invites retrying."""
        assert rate_limit.retry_phrase(900) == "in about 15 minutes"
        assert rate_limit.retry_phrase(45) == "in 45 seconds"
        assert rate_limit.retry_phrase(0) == "shortly"
