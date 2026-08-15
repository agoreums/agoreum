"""Health endpoint tests.

These assert the honesty of the readiness contract: readiness must report the true
state of dependencies and must never return success when a dependency is unreachable.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app.modules.health import service


async def test_liveness_is_independent_of_dependencies(client: AsyncClient) -> None:
    """Liveness must succeed without touching the database or Redis."""
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Agoreum API"


async def test_liveness_sets_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.headers.get("X-Request-ID")


async def test_request_id_is_echoed_when_valid(client: AsyncClient) -> None:
    valid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    response = await client.get(
        "/api/v1/health/live", headers={"X-Request-ID": valid}
    )

    assert response.headers["X-Request-ID"] == valid


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    """A non-UUID inbound ID must not be reflected back into logs or responses."""
    response = await client.get(
        "/api/v1/health/live", headers={"X-Request-ID": "not-a-uuid\ninjected"}
    )

    assert response.headers["X-Request-ID"] != "not-a-uuid\ninjected"


async def test_security_headers_applied(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


async def test_readiness_reports_component_status(client: AsyncClient) -> None:
    """Readiness reports every probed component and never hides a failure.

    This test does not require Postgres or Redis to be running: it asserts the
    shape and the honesty of the contract either way. When a dependency is down
    the endpoint must return 503 and name the component that failed.
    """
    response = await client.get("/api/v1/health/ready")
    body = response.json()

    assert set(body["components"]) == {"database", "redis", "chain"}
    assert body["status"] in {"ok", "degraded", "down"}

    # Only the dependencies the service genuinely cannot run without decide
    # readiness. The chain is reported but does not take the site out of
    # rotation, and which components count is stated in the response.
    assert set(body["required_components"]) == {"database", "redis"}

    required_down = [
        name
        for name in body["required_components"]
        if body["components"][name]["status"] == "down"
    ]

    if required_down:
        assert response.status_code == 503
        assert body["status"] == "down"
        for name in required_down:
            assert body["components"][name]["error"], (
                f"component {name} is down but reported no error"
            )
    else:
        assert response.status_code == 200


async def test_chain_health_is_reported_but_not_required(
    client: AsyncClient,
) -> None:
    """An RPC provider outage must not take the whole platform out of rotation.

    Funding a new escrow already fails loudly on its own; degrading is a better
    outcome than going dark over a third party.
    """
    body = (await client.get("/api/v1/health/ready")).json()

    assert "chain" in body["components"]
    assert "chain" not in body["required_components"]


class _CountingChain:
    """A stand-in RPC endpoint that records how often it was actually called."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def __call__(self) -> dict[str, object]:
        self.calls += 1
        # A real round-trip is not instant, which is what lets concurrent
        # callers pile up behind an uncached probe.
        await asyncio.sleep(0.01)
        if self.fail:
            raise ConnectionError("rpc unreachable")
        return {"status": "ok", "network": "base-sepolia", "head_block": 1}


@pytest.fixture
def counting_chain(monkeypatch):
    def _install(*, fail: bool = False) -> _CountingChain:
        probe = _CountingChain(fail=fail)
        monkeypatch.setattr("app.chain.client.health_check", probe)
        return probe

    return _install


async def test_a_burst_of_readiness_checks_costs_one_rpc_call(
    client: AsyncClient, counting_chain
) -> None:
    """The readiness probe must not bill an RPC call per request.

    It is unauthenticated, and the container healthcheck alone asks every 30
    seconds. Uncached, each caller forced an outbound round-trip, which load
    testing measured as the cap on the whole API's throughput. Twenty concurrent
    callers must produce one call, not twenty.
    """
    probe = counting_chain()

    await asyncio.gather(*[client.get("/api/v1/health/ready") for _ in range(20)])

    assert probe.calls == 1, f"{probe.calls} RPC calls for one burst of checks"


async def test_the_cached_chain_answer_carries_its_age(
    client: AsyncClient, counting_chain
) -> None:
    """A reader must be able to tell the figure predates their request."""
    counting_chain()

    first = (await client.get("/api/v1/health/ready")).json()["components"]["chain"]
    second = (await client.get("/api/v1/health/ready")).json()["components"]["chain"]

    assert "age_seconds" not in first, "a freshly measured probe claimed an age"
    assert "age_seconds" in second, "a cached probe did not disclose its age"


async def test_the_cache_expires_rather_than_pinning_a_stale_verdict(
    client: AsyncClient, counting_chain, monkeypatch
) -> None:
    """Caching must not turn a recovered chain into a permanently down one."""
    probe = counting_chain()
    monkeypatch.setattr(service, "CHAIN_CACHE_SECONDS", 0.05)

    await client.get("/api/v1/health/ready")
    await asyncio.sleep(0.08)
    await client.get("/api/v1/health/ready")

    assert probe.calls == 2, "the probe never re-measured after the window passed"


async def test_a_failing_provider_is_not_hammered_by_our_own_health_checks(
    client: AsyncClient, counting_chain
) -> None:
    """Failures are cached too.

    An RPC provider having an outage is the worst moment to multiply our request
    rate against it, and a failure is exactly when health checks get polled hard.
    """
    probe = counting_chain(fail=True)

    bodies = [
        (await client.get("/api/v1/health/ready")).json() for _ in range(5)
    ]

    assert probe.calls == 1, f"a failing provider was called {probe.calls} times"
    assert all(b["components"]["chain"]["status"] == "down" for b in bodies)
    # Still reported, still not fatal: the site stays in rotation.
    assert all("chain" not in b["required_components"] for b in bodies)


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert "request_id" in body["error"]


class _FakeRedis:
    """A Redis stand-in answering per key, or raising.

    Per key on purpose. Every worker check calls the same `create_client`, so a
    fake that returns one value for all of them makes each worker's health
    depend on the others. The first version of these tests did that, and a
    mutation excluding the emails worker from the overall status still passed,
    because the 503 it asserted was coming from the webhooks worker instead.
    """

    def __init__(self, values: dict[str, str | None] | None = None, fail: bool = False) -> None:
        self._values = values or {}
        self._fail = fail
        self.asked: list[str] = []

    async def get(self, key: str):
        self.asked.append(key)
        if self._fail:
            raise ConnectionError("redis unreachable")
        return self._values.get(key)

    async def aclose(self) -> None:
        return None


class TestEveryRunningWorkerIsWatched:
    """The emails worker ran in production with nothing watching it.

    `/health/workers` reported the subscription indexer and the webhooks worker
    and looked complete. Production runs four workers besides the monitor, and
    the one with no heartbeat was the one that sends sign-in alerts and email
    verification links.

    That silence is the hardest kind to notice from outside, because nobody
    reports mail they were never expecting. A wedged loop would have looked
    exactly like a quiet week.

    The fix generalised the check rather than copying it, so these assert the
    general shape and not one worker's spelling.
    """

    async def test_the_endpoint_reports_the_emails_worker(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        import time as _time

        from app.modules.health import service as health

        now = str(int(_time.time()))
        fresh = _FakeRedis(dict.fromkeys(health.WORKER_HEARTBEAT_KEYS.values(), now))
        monkeypatch.setattr("app.core.redis.create_client", lambda **_: fresh)

        body = (await client.get("/api/v1/health/workers")).json()
        assert "emails_worker" in body, (
            "the emails worker is not reported, so a stalled loop is invisible"
        )
        assert body["emails_worker"]["status"] == "ok"

    async def test_a_stalled_email_loop_is_reported_down(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """The case that matters: the container is up and the loop is not."""
        import time as _time

        from app.modules.health import service as health

        now = int(_time.time())
        stale = now - (health.WORKER_HEARTBEAT_STALE_SECONDS + 60)
        # Only the emails worker is stale. Everything else this endpoint can see
        # is healthy, so a 503 can only be coming from the emails worker.
        monkeypatch.setattr(
            "app.core.redis.create_client",
            lambda **_: _FakeRedis(
                {
                    health.WEBHOOK_HEARTBEAT_KEY: str(now),
                    health.EMAIL_HEARTBEAT_KEY: str(stale),
                }
            ),
        )

        resp = await client.get("/api/v1/health/workers")
        body = resp.json()
        assert body["emails_worker"]["status"] == "down"
        assert body["webhooks_worker"]["status"] == "ok", "the other worker must be healthy here"
        assert body["status"] == "down", (
            "a stopped emails worker did not reach the overall status, so the "
            "endpoint would report healthy and the monitor would never alert"
        )
        assert resp.status_code == 503, (
            "a stopped worker must fail the endpoint, or the monitor never sees it"
        )

    async def test_a_worker_that_never_ran_is_distinguished_from_a_stalled_one(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """No heartbeat at all is a fresh deploy, not a stalled loop.

        Reporting it as down would page somebody every release, and an alert
        that cries wolf on every deploy is one people learn to close.
        """

        monkeypatch.setattr("app.core.redis.create_client", lambda **_: _FakeRedis({}))

        body = (await client.get("/api/v1/health/workers")).json()
        assert body["emails_worker"]["status"] == "degraded"

    async def test_an_unreachable_redis_does_not_read_as_a_healthy_worker(
        self, client: AsyncClient, monkeypatch
    ) -> None:

        monkeypatch.setattr("app.core.redis.create_client", lambda **_: _FakeRedis(fail=True))

        body = (await client.get("/api/v1/health/workers")).json()
        assert body["emails_worker"]["status"] == "down"

    async def test_each_watched_worker_has_its_own_heartbeat_key(self) -> None:
        """Otherwise two workers share a key and one masks the other's death."""
        from app.modules.health import service as health

        keys = list(health.WORKER_HEARTBEAT_KEYS.values())
        assert len(keys) == len(set(keys)), f"heartbeat keys collide: {keys}"
        assert "emails_worker" in health.WORKER_HEARTBEAT_KEYS

    def test_the_worker_that_writes_the_heartbeat_uses_the_same_key(self) -> None:
        """The reader and the writer must agree, and they live in different files.

        A renamed constant on one side would leave the endpoint reading a key
        nobody writes, which reports a healthy worker as permanently degraded,
        or worse, reports a dead one as fine if the default ever changed.
        """
        from pathlib import Path

        from app.modules.health import service as health

        cli = Path(health.__file__).resolve().parents[2] / "cli.py"
        source = cli.read_text(encoding="utf-8")
        # The shared constant, not merely the name. A local variable of the same
        # name would satisfy a substring check while writing a different key,
        # which is exactly what a mutation of this test proved.
        assert "from app.modules.health.service import EMAIL_HEARTBEAT_KEY" in source, (
            "the emails worker no longer imports the heartbeat key the endpoint reads"
        )
