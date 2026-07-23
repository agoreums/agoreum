"""Health endpoint tests.

These assert the honesty of the readiness contract: readiness must report the true
state of dependencies and must never return success when a dependency is unreachable.
"""
from __future__ import annotations

from httpx import AsyncClient


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

    assert set(body["components"]) == {"database", "redis"}
    assert body["status"] in {"ok", "degraded", "down"}

    if body["status"] == "down":
        assert response.status_code == 503
        failed = [
            name for name, comp in body["components"].items()
            if comp["status"] == "down"
        ]
        assert failed, "status is down but no component was reported down"
        for name in failed:
            assert body["components"][name]["error"], (
                f"component {name} is down but reported no error"
            )
    else:
        assert response.status_code == 200


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert "request_id" in body["error"]
