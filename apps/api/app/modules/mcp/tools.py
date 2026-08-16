"""The tools an outside agent can call, and what each one costs in scope.

Why an MCP server exists at all. Research in August 2026 found MCP carries the
developer weight in this space by roughly two orders of magnitude over the
alternatives, and that runtime discovery through registries is mostly
aspirational: in practice a person adds one connector to an agent's
configuration, and from then on the agent uses it. That shapes the design. This
is **one** server exposing the whole catalogue, not one server per listing, so a
single connector buys an agent access to everything Agoreum knows about.

Two rules run through this file and are not negotiable.

**A tool description is not interface copy.** Copy on a web page is read by a
person who can notice it is wrong. A tool description and a tool result go
straight into another agent's context with no human in the loop. So every result
that touches money carries the network it settles on, in the result itself, not
in documentation somebody might read. A tool that let another agent believe this
was mainnet would be a fabrication delivered directly into its reasoning.

**Scopes are declared as data.** Each tool names the scopes it needs, and a test
asserts every registered tool appears in that table. Enforcement that depends on
whoever adds the next tool remembering to add a check is the shape of defect this
project has spent weeks removing.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import settings

# Repeated into every result that concerns money. Deliberately not a footnote:
# an agent reading this has no other way to learn it, and the difference between
# test currency and money is the single fact it most needs.
SETTLEMENT_NOTICE = (
    "Settlement is on Base Sepolia, a test network. The USDC here is test "
    "currency with no real value. Nothing is deployed to mainnet."
)


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    scopes: frozenset[str]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    # Whether the result concerns money and must carry the settlement notice.
    touches_money: bool = False


def _page(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


async def _chain_status(db: AsyncSession, principal: Principal, **_: Any) -> dict[str, Any]:
    """Deliberately the first tool, and callable without any scope.

    An agent deciding whether to spend should be able to establish what network
    it is dealing with before it does anything else, without needing permission
    to ask.
    """
    return {
        "chain_id": settings.CHAIN_ID,
        "network": "base-sepolia",
        "is_testnet": True,
        "settlement_token": "USDC (test)",
        "notice": SETTLEMENT_NOTICE,
    }


async def _search_services(
    db: AsyncSession, principal: Principal, **kwargs: Any
) -> dict[str, Any]:
    from app.modules.marketplace import service as marketplace
    from app.modules.marketplace.schemas import ServiceSearchParams

    limit = int(kwargs.get("limit") or 20)
    offset = int(kwargs.get("offset") or 0)
    params = ServiceSearchParams(
        q=kwargs.get("q"),
        category=kwargs.get("category"),
        tags=kwargs.get("tags") or [],
        max_delivery_hours=kwargs.get("max_delivery_hours"),
        min_price=_decimal(kwargs.get("min_price")),
        max_price=_decimal(kwargs.get("max_price")),
        limit=limit,
        offset=offset,
    )
    rows, total, _ = await marketplace.search_services(db, params)
    return {
        **_page([_service_summary(s) for s in rows], total, limit, offset),
        "notice": SETTLEMENT_NOTICE,
    }


async def _get_agent(db: AsyncSession, principal: Principal, **kwargs: Any) -> dict[str, Any]:
    from app.modules.agents import service as agents

    agent = await agents.require_agent(db, str(kwargs["slug"]))
    return {
        "slug": agent.slug,
        "name": agent.name,
        "tagline": agent.tagline,
        "description": agent.description,
        "verification_tier": _enum(agent.verification_tier),
        "published": agent.published_at is not None,
    }


async def _get_agent_reputation(
    db: AsyncSession, principal: Principal, **kwargs: Any
) -> dict[str, Any]:
    from app.modules.agents import service as agents
    from app.modules.reputation import service as reputation

    agent = await agents.require_agent(db, str(kwargs["slug"]))
    summary = await reputation.summary_for(db, agent=agent)
    payload = summary if isinstance(summary, dict) else _as_dict(summary)
    # The provenance is the point of this number and an agent cannot infer it.
    payload["basis"] = (
        "Computed only from orders that settled through on-chain escrow. "
        "Nothing is seeded, self-reported, or purchasable."
    )
    payload["notice"] = SETTLEMENT_NOTICE
    return payload


async def _list_my_agents(
    db: AsyncSession, principal: Principal, **_: Any
) -> dict[str, Any]:
    from app.modules.agents import service as agents

    rows = await agents.list_for_user(db, user_id=principal.user.id)
    return {"items": [{"slug": a.slug, "name": a.name} for a in rows], "total": len(rows)}


async def _list_my_orders(
    db: AsyncSession, principal: Principal, **_: Any
) -> dict[str, Any]:
    from app.modules.orders import service as orders

    rows = await orders.list_for_buyer(db, user=principal.user)
    return {
        "items": [_order_summary(o) for o in rows],
        "total": len(rows),
        "notice": SETTLEMENT_NOTICE,
    }


async def _get_order(db: AsyncSession, principal: Principal, **kwargs: Any) -> dict[str, Any]:
    import uuid as _uuid

    from app.modules.orders import service as orders

    order = await orders.require_visible_order(
        db, _uuid.UUID(str(kwargs["order_id"])), user=principal.user
    )
    return {**_order_summary(order), "notice": SETTLEMENT_NOTICE}


REGISTRY: tuple[Tool, ...] = (
    Tool(
        name="chain_status",
        title="Which network this settles on",
        description=(
            "Report the chain Agoreum settles on and whether it is a test "
            "network. Call this before anything involving payment. "
            + SETTLEMENT_NOTICE
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        scopes=frozenset(),
        handler=_chain_status,
        touches_money=True,
    ),
    Tool(
        name="search_services",
        title="Search the marketplace",
        description=(
            "Full-text search across published services, with filters for "
            "category, tags, price and delivery time. Returns real listings "
            "only; nothing here is seeded or synthetic. " + SETTLEMENT_NOTICE
        ),
        input_schema={
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Free text query", "maxLength": 200},
                "category": {"type": "string", "maxLength": 64},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "max_delivery_hours": {"type": "integer", "minimum": 1, "maximum": 8760},
                "min_price": {"type": "number", "minimum": 0},
                "max_price": {"type": "number", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
            },
            "additionalProperties": False,
        },
        scopes=frozenset({"marketplace:read"}),
        handler=_search_services,
        touches_money=True,
    ),
    Tool(
        name="get_agent",
        title="Read an agent's public profile",
        description="Fetch one agent by slug, including its verification tier.",
        input_schema={
            "type": "object",
            "properties": {"slug": {"type": "string", "maxLength": 64}},
            "required": ["slug"],
            "additionalProperties": False,
        },
        scopes=frozenset({"marketplace:read"}),
        handler=_get_agent,
    ),
    Tool(
        name="get_agent_reputation",
        title="Read an agent's reputation and where it came from",
        description=(
            "Reputation for one agent, computed only from orders that settled "
            "through on-chain escrow. The result states its own basis, because "
            "a score without provenance is not evidence. " + SETTLEMENT_NOTICE
        ),
        input_schema={
            "type": "object",
            "properties": {"slug": {"type": "string", "maxLength": 64}},
            "required": ["slug"],
            "additionalProperties": False,
        },
        scopes=frozenset({"marketplace:read"}),
        handler=_get_agent_reputation,
        touches_money=True,
    ),
    Tool(
        name="list_my_agents",
        title="List the agents this key owns",
        description="Agents belonging to the organization this API key was minted in.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        scopes=frozenset({"agents:read"}),
        handler=_list_my_agents,
    ),
    Tool(
        name="list_my_orders",
        title="List orders placed by this account",
        description="Orders this account has placed, newest first. " + SETTLEMENT_NOTICE,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        scopes=frozenset({"orders:read"}),
        handler=_list_my_orders,
        touches_money=True,
    ),
    Tool(
        name="get_order",
        title="Read one order",
        description=(
            "Fetch a single order this account is party to, with its status and "
            "escrow detail. " + SETTLEMENT_NOTICE
        ),
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string", "format": "uuid"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        scopes=frozenset({"orders:read"}),
        handler=_get_order,
        touches_money=True,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in REGISTRY}


# --- helpers ----------------------------------------------------------------


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value or {})


def _service_summary(service: Any) -> dict[str, Any]:
    return {
        "slug": service.slug,
        "title": service.title,
        "summary": service.summary,
        "pricing_model": _enum(service.pricing_model),
        "price": str(service.price) if service.price is not None else None,
        "price_currency": getattr(service, "price_currency", None),
        "delivery_time_hours": service.delivery_time_hours,
        "agent_slug": getattr(getattr(service, "agent", None), "slug", None),
    }


def _order_summary(order: Any) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "reference": getattr(order, "reference", None),
        "status": _enum(order.status),
        "quantity": order.quantity,
        "subtotal": str(order.subtotal) if order.subtotal is not None else None,
        "currency": getattr(order, "currency", None),
        "funding_deadline": _iso(getattr(order, "funding_deadline", None)),
        "auto_release_at": _iso(getattr(order, "auto_release_at", None)),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
