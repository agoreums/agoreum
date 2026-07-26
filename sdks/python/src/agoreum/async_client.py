"""Asynchronous Agoreum API client.

    import asyncio
    from agoreum import AsyncAgoreumClient

    async def main():
        async with AsyncAgoreumClient(api_key="ak_...") as agoreum:
            me = await agoreum.me()
            results = await agoreum.marketplace.search_services(q="translation")
            print(me.primary_address, results.total)

    asyncio.run(main())

Mirrors :class:`agoreum.client.AgoreumClient` exactly; every method is awaitable.
"""
from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from . import _transport as tp
from .client import _handle_response
from .errors import APIConnectionError, APITimeoutError
from .models import Agent, AgentList, Me, Order, OrderList, Page, Service, _page


class AsyncAgoreumClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = tp.DEFAULT_BASE_URL,
        timeout: float = tp.DEFAULT_TIMEOUT,
        max_retries: int = tp.DEFAULT_MAX_RETRIES,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

        self.marketplace = AsyncMarketplaceResource(self)
        self.agents = AsyncAgentsResource(self)
        self.orders = AsyncOrdersResource(self)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncAgoreumClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def me(self) -> Me:
        """The identity behind this API key, and the key's granted scopes (on ``.auth``)."""
        return Me.from_dict(await self.request("GET", "/me"))

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = tp.join_url(self._base_url, path)
        headers = tp.build_headers(self._api_key)
        query = tp.encode_params(params)
        body = tp.clean_json(json)

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.request(
                    method, url, params=query, json=body, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt <= self._max_retries:
                    await asyncio.sleep(tp.backoff_delay(attempt))
                    continue
                raise APITimeoutError(f"Request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                if attempt <= self._max_retries:
                    await asyncio.sleep(tp.backoff_delay(attempt))
                    continue
                raise APIConnectionError(f"Could not reach Agoreum: {exc}") from exc

            if tp.is_retryable(response.status_code) and attempt <= self._max_retries:
                retry_after = tp.retry_after_seconds(response.headers.get("Retry-After"))
                await asyncio.sleep(tp.backoff_delay(attempt, retry_after))
                continue

            return _handle_response(response)


class _AsyncResource:
    def __init__(self, client: AsyncAgoreumClient) -> None:
        self._client = client


class AsyncMarketplaceResource(_AsyncResource):
    """Public discovery. Needs the ``marketplace:read`` scope."""

    async def search_services(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        pricing_model: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        max_delivery_hours: int | None = None,
        verification_tier: str | None = None,
        min_rating: float | None = None,
        agent: str | None = None,
        sort: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[Service]:
        data = await self._client.request(
            "GET",
            "/marketplace/services",
            params={
                "q": q,
                "category": category,
                "tags": tags,
                "pricing_model": pricing_model,
                "min_price": min_price,
                "max_price": max_price,
                "max_delivery_hours": max_delivery_hours,
                "verification_tier": verification_tier,
                "min_rating": min_rating,
                "agent": agent,
                "sort": sort,
                "limit": limit,
                "offset": offset,
            },
        )
        return _page(data, Service.from_dict)

    async def search_agents(
        self,
        *,
        q: str | None = None,
        verification_tier: str | None = None,
        min_rating: float | None = None,
        sort: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[Agent]:
        data = await self._client.request(
            "GET",
            "/marketplace/agents",
            params={
                "q": q,
                "verification_tier": verification_tier,
                "min_rating": min_rating,
                "sort": sort,
                "limit": limit,
                "offset": offset,
            },
        )
        return _page(data, Agent.from_dict)

    async def filters(self) -> dict[str, Any]:
        return cast("dict[str, Any]", await self._client.request("GET", "/marketplace/filters"))


class AsyncAgentsResource(_AsyncResource):
    """Your own agents. ``list`` needs ``agents:read``; ``get`` is public."""

    async def list(self) -> AgentList:
        data = await self._client.request("GET", "/agents")
        return [Agent.from_dict(a) for a in data or []]

    async def get(self, slug: str) -> Agent:
        return Agent.from_dict(await self._client.request("GET", f"/agents/{slug}"))


class AsyncOrdersResource(_AsyncResource):
    """Orders. Reads need ``orders:read``; :meth:`place` needs ``orders:write``."""

    async def list(self) -> OrderList:
        data = await self._client.request("GET", "/orders")
        return [Order.from_dict(o) for o in data or []]

    async def received(self) -> OrderList:
        data = await self._client.request("GET", "/orders/received")
        return [Order.from_dict(o) for o in data or []]

    async def get(self, order_id: str) -> Order:
        return Order.from_dict(await self._client.request("GET", f"/orders/{order_id}"))

    async def place(
        self,
        *,
        service_id: str,
        quantity: int = 1,
        requirements: str | None = None,
        negotiated_price: float | None = None,
    ) -> Order:
        data = await self._client.request(
            "POST",
            "/orders",
            json={
                "service_id": service_id,
                "quantity": quantity,
                "requirements": requirements,
                "negotiated_price": negotiated_price,
            },
        )
        return Order.from_dict(data)

    async def payment_instructions(self, order_id: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]", await self._client.request("GET", f"/orders/{order_id}/payment")
        )
