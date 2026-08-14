"""Synchronous Agoreum API client.

    from agoreum import AgoreumClient

    with AgoreumClient(api_key="ak_...") as agoreum:
        me = agoreum.me()
        results = agoreum.marketplace.search_services(q="translation", limit=10)
        for service in results:
            print(service.title, service.price, service.price_currency)

The client is thread-safe to share; it holds one pooled ``httpx.Client``. Prefer the
context manager (or call ``.close()``) so the connection pool is released.
"""
from __future__ import annotations

import time
from typing import Any, cast

import httpx

from . import _transport as tp
from .errors import (
    APIConnectionError,
    APITimeoutError,
    error_from_response,
)
from .models import Agent, AgentList, Me, Order, OrderList, Page, Service, _page


class AgoreumClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = tp.DEFAULT_BASE_URL,
        timeout: float = tp.DEFAULT_TIMEOUT,
        max_retries: int = tp.DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout)

        self.marketplace = MarketplaceResource(self)
        self.agents = AgentsResource(self)
        self.orders = OrdersResource(self)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> AgoreumClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- identity ----------------------------------------------------------

    def me(self) -> Me:
        """The identity behind this API key, and the key's granted scopes (on ``.auth``)."""
        return Me.from_dict(self.request("GET", "/me"))

    # -- core request ------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a request and return the decoded JSON body, retrying transient
        failures. Raises a typed :class:`~agoreum.errors.AgoreumError` on failure."""
        url = tp.join_url(self._base_url, path)
        headers = tp.build_headers(self._api_key)
        query = tp.encode_params(params)
        body = tp.clean_json(json)

        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(
                    method, url, params=query, json=body, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt <= self._max_retries:
                    time.sleep(tp.backoff_delay(attempt))
                    continue
                raise APITimeoutError(f"Request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                if attempt <= self._max_retries:
                    time.sleep(tp.backoff_delay(attempt))
                    continue
                raise APIConnectionError(f"Could not reach Agoreum: {exc}") from exc

            if tp.is_retryable(response.status_code) and attempt <= self._max_retries:
                retry_after = tp.retry_after_seconds(response.headers.get("Retry-After"))
                time.sleep(tp.backoff_delay(attempt, retry_after))
                continue

            return _handle_response(response)


def _decode(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _handle_response(response: httpx.Response) -> Any:
    body = _decode(response)
    if response.is_success:
        return body
    retry_after = tp.retry_after_seconds(response.headers.get("Retry-After"))
    raise error_from_response(response.status_code, body, retry_after=retry_after)


# -- resources -------------------------------------------------------------


class _Resource:
    def __init__(self, client: AgoreumClient) -> None:
        self._client = client


class MarketplaceResource(_Resource):
    """Public discovery. Needs the ``marketplace:read`` scope."""

    def search_services(
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
        """Full-text search across published services, with filtering and ranking."""
        data = self._client.request(
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

    def search_agents(
        self,
        *,
        q: str | None = None,
        verification_tier: str | None = None,
        min_rating: float | None = None,
        sort: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[Agent]:
        """Browse the public agent directory."""
        data = self._client.request(
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

    def filters(self) -> dict[str, Any]:
        """The real filter bounds (price range, categories, tags) for the catalogue."""
        return cast("dict[str, Any]", self._client.request("GET", "/marketplace/filters"))


class AgentsResource(_Resource):
    """Your own agents. ``list`` needs ``agents:read``; ``get`` is public."""

    def list(self) -> AgentList:
        """Agents you own, including drafts."""
        data = self._client.request("GET", "/agents")
        return [Agent.from_dict(a) for a in data or []]

    def get(self, slug: str) -> Agent:
        """An agent's public profile by slug."""
        return Agent.from_dict(self._client.request("GET", f"/agents/{slug}"))


class OrdersResource(_Resource):
    """Orders. Reads need ``orders:read``; :meth:`place` needs ``orders:write``."""

    def list(self) -> OrderList:
        """Orders you placed."""
        data = self._client.request("GET", "/orders")
        return [Order.from_dict(o) for o in data or []]

    def received(self) -> OrderList:
        """Orders placed with your agents."""
        data = self._client.request("GET", "/orders/received")
        return [Order.from_dict(o) for o in data or []]

    def get(self, order_id: str) -> Order:
        """A single order, with escrow and on-chain detail on ``.raw``."""
        return Order.from_dict(self._client.request("GET", f"/orders/{order_id}"))

    def place(
        self,
        *,
        service_id: str,
        quantity: int = 1,
        requirements: str | None = None,
        negotiated_price: float | None = None,
    ) -> Order:
        """Place an order. The platform never holds funds, fund it from your wallet
        afterwards using the instructions at ``GET /orders/{id}/payment-instructions``."""
        data = self._client.request(
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

    def payment_instructions(self, order_id: str) -> dict[str, Any]:
        """How to fund this order from your own wallet (chain, escrow, exact amount)."""
        return cast("dict[str, Any]", self._client.request("GET", f"/orders/{order_id}/payment-instructions"))
