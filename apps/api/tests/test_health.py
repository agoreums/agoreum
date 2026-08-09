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
