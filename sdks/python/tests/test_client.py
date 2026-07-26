"""Tests for the Agoreum Python SDK, with the HTTP layer mocked by respx.

No network is touched. These assert the SDK's contract: correct paths and headers
go out, real response shapes parse into typed models, and the error envelope maps
onto the right exception class.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from agoreum import (
    AgoreumClient,
    AsyncAgoreumClient,
    AuthenticationError,
    InsufficientScopeError,
    NotFoundError,
    RateLimitError,
    Service,
)

BASE = "https://agoreum.xyz/api/v1"

ME = {
    "id": "11111111-1111-1111-1111-111111111111",
    "username": "acme",
    "display_name": "Acme Labs",
    "primary_address": "0xf688A25DB028dE3FfC670c0C5A79ee1A5E9BD90A",
    "role": "user",
    "created_at": "2026-07-01T12:00:00Z",
    "auth": {"via_api_key": True, "scopes": ["marketplace:read", "orders:read"]},
}

SERVICE_PAGE = {
    "items": [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "slug": "fast-translation",
            "title": "Fast Translation",
            "summary": "Human-quality translation in minutes.",
            "pricing_model": "fixed",
            "price": "12.500000",
            "price_currency": "USDC",
            "price_unit": "per document",
            "delivery_time_hours": 24,
            "tags": ["translation", "localization"],
            "completed_order_count": 42,
            "review_count": 30,
            "average_rating": 4.8,
            "agent": {
                "id": "33333333-3333-3333-3333-333333333333",
                "slug": "acme-translate",
                "name": "Acme Translate",
                "verification_tier": "domain",
            },
        }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0,
    "query": "translation",
    "sort": "relevance",
}


def _err(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


@respx.mock
def test_me_sends_api_key_and_parses() -> None:
    route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME))
    with AgoreumClient(api_key="ak_test") as client:
        me = client.me()
    assert route.called
    assert route.calls.last.request.headers["X-API-Key"] == "ak_test"
    assert route.calls.last.request.headers["User-Agent"].startswith("agoreum-python/")
    assert me.username == "acme"
    assert me.auth["scopes"] == ["marketplace:read", "orders:read"]


@respx.mock
def test_search_services_params_and_model() -> None:
    route = respx.get(f"{BASE}/marketplace/services").mock(
        return_value=httpx.Response(200, json=SERVICE_PAGE)
    )
    with AgoreumClient(api_key="ak_test") as client:
        page = client.marketplace.search_services(
            q="translation", tags=["translation", "localization"], min_rating=4.0, limit=20
        )
    url = route.calls.last.request.url
    assert url.params["q"] == "translation"
    assert url.params.get_list("tags") == ["translation", "localization"]
    assert url.params["min_rating"] == "4.0"

    assert page.total == 1
    assert not page.has_more
    service = page.items[0]
    assert isinstance(service, Service)
    assert service.price == Decimal("12.500000")
    assert service.agent is not None
    assert service.agent.slug == "acme-translate"
    # Page is directly iterable.
    assert [s.slug for s in page] == ["fast-translation"]


@respx.mock
def test_place_order_posts_body_without_nulls() -> None:
    order = {
        "id": "44444444-4444-4444-4444-444444444444",
        "reference": "AGO-0001",
        "status": "pending_payment",
        "quantity": 2,
        "unit_price": "12.500000",
        "subtotal": "25.000000",
        "platform_fee": "0.500000",
        "total_amount": "25.500000",
        "currency": "USDC",
        "platform_fee_bps": 200,
        "created_at": "2026-07-26T10:00:00Z",
    }
    route = respx.post(f"{BASE}/orders").mock(return_value=httpx.Response(201, json=order))
    with AgoreumClient(api_key="ak_test") as client:
        placed = client.orders.place(service_id="svc-1", quantity=2)
    body = route.calls.last.request.content.decode()
    assert '"service_id": "svc-1"' in body or '"service_id":"svc-1"' in body
    # negotiated_price was None and must be omitted, not sent as null.
    assert "negotiated_price" not in body
    assert placed.reference == "AGO-0001"
    assert placed.total_amount == Decimal("25.500000")


@respx.mock
def test_error_envelope_maps_to_typed_exceptions() -> None:
    respx.get(f"{BASE}/me").mock(
        return_value=httpx.Response(401, json=_err("unauthenticated", "Provide an API key."))
    )
    with AgoreumClient(api_key="ak_bad") as client, pytest.raises(AuthenticationError) as exc:
        client.me()
    assert exc.value.code == "unauthenticated"
    assert exc.value.status_code == 401


@respx.mock
def test_not_found() -> None:
    respx.get(f"{BASE}/agents/ghost").mock(
        return_value=httpx.Response(404, json=_err("not_found", "No such agent."))
    )
    with AgoreumClient(api_key="ak_test") as client, pytest.raises(NotFoundError):
        client.agents.get("ghost")


@respx.mock
def test_insufficient_scope_is_distinct() -> None:
    respx.get(f"{BASE}/orders").mock(
        return_value=httpx.Response(
            403,
            json=_err(
                "insufficient_scope",
                "This API key is missing the required scope(s): orders:read.",
                details={"missing": ["orders:read"]},
            ),
        )
    )
    with (
        AgoreumClient(api_key="ak_test") as client,
        pytest.raises(InsufficientScopeError) as exc,
    ):
        client.orders.list()
    assert exc.value.details["missing"] == ["orders:read"]


@respx.mock
def test_retries_on_429_then_succeeds() -> None:
    route = respx.get(f"{BASE}/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json=_err("rate_limited", "Slow down.")),
            httpx.Response(200, json=ME),
        ]
    )
    with AgoreumClient(api_key="ak_test", max_retries=2) as client:
        me = client.me()
    assert route.call_count == 2
    assert me.username == "acme"


@respx.mock
def test_gives_up_after_max_retries() -> None:
    respx.get(f"{BASE}/me").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"}, json=_err("rate_limited", "Slow down."))
    )
    with (
        AgoreumClient(api_key="ak_test", max_retries=1) as client,
        pytest.raises(RateLimitError),
    ):
        client.me()


def test_api_key_required() -> None:
    with pytest.raises(ValueError):
        AgoreumClient(api_key="")


@respx.mock
async def test_async_client_parses() -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{BASE}/marketplace/services").mock(
        return_value=httpx.Response(200, json=SERVICE_PAGE)
    )
    async with AsyncAgoreumClient(api_key="ak_test") as client:
        me = await client.me()
        page = await client.marketplace.search_services(q="translation")
    assert me.display_name == "Acme Labs"
    assert page.items[0].title == "Fast Translation"
