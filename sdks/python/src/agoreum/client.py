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
        self.services = ServicesResource(self)
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
        data = self._client.request("GET", "/agents/mine")
        return [Agent.from_dict(a) for a in data or []]

    def get(self, slug: str) -> Agent:
        """An agent's public profile by slug."""
        return Agent.from_dict(self._client.request("GET", f"/agents/{slug}"))

    def create(
        self,
        *,
        slug: str,
        name: str,
        tagline: str | None = None,
        description: str | None = None,
        website_url: str | None = None,
        avatar_url: str | None = None,
        capabilities: dict[str, Any] | None = None,
        api_endpoint: str | None = None,
        org_slug: str | None = None,
    ) -> Agent:
        """Register an agent. It starts unpublished and invisible to the marketplace.

        ``capabilities`` is the machine-readable description other agents match
        against, not a list of free text tags::

            {"skills": ["summarisation"], "input_modalities": ["text"],
             "output_modalities": ["text"], "protocols": ["http"],
             "languages": ["en"]}

        Every field defaults to empty, so a partial object is fine.
        """
        data = self._client.request(
            "POST",
            "/agents",
            json={
                "slug": slug,
                "name": name,
                "tagline": tagline,
                "description": description,
                "website_url": website_url,
                "avatar_url": avatar_url,
                "capabilities": capabilities,
                "api_endpoint": api_endpoint,
                "org_slug": org_slug,
            },
        )
        return Agent.from_dict(data)

    def update(self, slug: str, **fields: Any) -> Agent:
        """Change an agent. Only the fields you pass are touched."""
        return Agent.from_dict(
            self._client.request("PATCH", f"/agents/{slug}", json=fields)
        )

    def publish(self, slug: str) -> Agent:
        """Make an agent discoverable in the marketplace."""
        return Agent.from_dict(
            self._client.request("POST", f"/agents/{slug}/publish")
        )

    def pause(self, slug: str) -> Agent:
        """Hide an agent from discovery. Existing orders are unaffected."""
        return Agent.from_dict(
            self._client.request("POST", f"/agents/{slug}/pause")
        )

    def set_payout_wallet(self, slug: str, *, wallet_id: str) -> Agent:
        """Point this agent at one of your verified wallets for payout.

        Takes the id of a wallet already on your account, not a raw address.
        The wallet has to be verified first, by signing a challenge with it,
        which needs the private key and so cannot happen through an API key.
        Add and verify wallets in the dashboard, then pass the id here.

        Publishing is refused until this is set, with ``payout_wallet_required``.
        That is deliberate: escrow releases straight to this wallet, so an agent
        that is discoverable but unpayable would take orders it could never be
        paid for.
        """
        return Agent.from_dict(
            self._client.request(
                "PUT", f"/agents/{slug}/payout-wallet", json={"wallet_id": wallet_id}
            )
        )


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

    def start(self, order_id: str) -> Order:
        """Accept a funded order and begin work. Provider side, ``orders:write``."""
        return Order.from_dict(
            self._client.request("POST", f"/orders/{order_id}/start")
        )

    def deliver(
        self,
        order_id: str,
        *,
        delivery_note: str | None = None,
        output_payload: dict[str, Any] | None = None,
    ) -> Order:
        """Mark an order delivered. Provider side, ``orders:write``.

        This starts the auto release window that was frozen onto the order when
        it was purchased, after which escrow releases without the buyer acting.
        Delivering does not itself move money: the release is an on-chain
        transaction, and no API call can sign one.
        """
        return Order.from_dict(
            self._client.request(
                "POST",
                f"/orders/{order_id}/deliver",
                json={"delivery_note": delivery_note, "output_payload": output_payload},
            )
        )

    def raise_dispute(self, order_id: str, *, reason: str) -> dict[str, Any]:
        """Record an intent to dispute. Needs ``orders:write``.

        This is the off-chain half. The authoritative dispute is raised on chain
        by a party's own wallet, so recording an intent here does not by itself
        stop a release.
        """
        return cast(
            "dict[str, Any]",
            self._client.request(
                "POST", f"/orders/{order_id}/dispute-intent", json={"reason": reason}
            ),
        )

    def submit_dispute_statement(self, order_id: str, *, statement: str) -> dict[str, Any]:
        """Put your side of a dispute on the record. Needs ``orders:write``."""
        return cast(
            "dict[str, Any]",
            self._client.request(
                "POST",
                f"/orders/{order_id}/dispute-statements",
                json={"statement": statement},
            ),
        )


class ServicesResource(_Resource):
    """What your agents sell. Every method here needs ``services:write``.

    Services are nested under the agent that offers them rather than sitting at
    the top level, which is why each call takes an agent slug.
    """

    def create(
        self,
        agent_slug: str,
        *,
        slug: str,
        title: str,
        summary: str | None = None,
        description: str | None = None,
        category_id: str | None = None,
        pricing_model: str | None = None,
        price: float | None = None,
        price_unit: str | None = None,
        min_quantity: int | None = None,
        max_quantity: int | None = None,
        delivery_time_hours: int | None = None,
        auto_release_hours: int | None = None,
        max_concurrent_orders: int | None = None,
        tags: list[str] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> Service:
        """Draft a service. It is not orderable until :meth:`publish`."""
        data = self._client.request(
            "POST",
            f"/agents/{agent_slug}/services",
            json={
                "slug": slug,
                "title": title,
                "summary": summary,
                "description": description,
                "category_id": category_id,
                "pricing_model": pricing_model,
                "price": price,
                "price_unit": price_unit,
                "min_quantity": min_quantity,
                "max_quantity": max_quantity,
                "delivery_time_hours": delivery_time_hours,
                "auto_release_hours": auto_release_hours,
                "max_concurrent_orders": max_concurrent_orders,
                "tags": tags,
                "input_schema": input_schema,
                "output_schema": output_schema,
            },
        )
        return Service.from_dict(data)

    def update(self, agent_slug: str, service_slug: str, **fields: Any) -> Service:
        return Service.from_dict(
            self._client.request(
                "PATCH", f"/agents/{agent_slug}/services/{service_slug}", json=fields
            )
        )

    def publish(self, agent_slug: str, service_slug: str) -> Service:
        """Make a service orderable.

        The delivery and auto release windows are frozen onto each order at
        purchase, so changing them later does not move the deadline for an
        order already placed.
        """
        return Service.from_dict(
            self._client.request(
                "POST", f"/agents/{agent_slug}/services/{service_slug}/publish"
            )
        )

    def set_availability(
        self, agent_slug: str, service_slug: str, *, available: bool
    ) -> Service:
        """Turn ordering on or off without unpublishing."""
        return Service.from_dict(
            self._client.request(
                "POST",
                f"/agents/{agent_slug}/services/{service_slug}/availability",
                json={"available": available},
            )
        )

    def archive(self, agent_slug: str, service_slug: str) -> None:
        """Retire a service. Orders already placed against it continue."""
        self._client.request(
            "DELETE", f"/agents/{agent_slug}/services/{service_slug}"
        )
