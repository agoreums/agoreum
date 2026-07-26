"""Typed models for Agoreum API responses.

Each model is a frozen dataclass built from the JSON the API returns. Parsing is
tolerant: unknown fields are ignored (so a newer server never breaks an older SDK),
and the untouched payload is always available on ``.raw`` for anything not yet
surfaced as an attribute. Timestamps are parsed to ``datetime`` and money to
``Decimal`` so callers never do that conversion themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Generic, Iterator, TypeVar

T = TypeVar("T")


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    # The API emits RFC 3339 with a trailing "Z"; fromisoformat handles "+00:00".
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


@dataclass(frozen=True)
class Me:
    """The identity behind the calling API key (``GET /me``)."""

    id: str
    primary_address: str
    role: str
    username: str | None = None
    display_name: str | None = None
    created_at: datetime | None = None
    auth: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Me":
        return cls(
            id=d["id"],
            primary_address=d["primary_address"],
            role=d.get("role", ""),
            username=d.get("username"),
            display_name=d.get("display_name"),
            created_at=_dt(d.get("created_at")),
            auth=d.get("auth") or {},
            raw=d,
        )


@dataclass(frozen=True)
class ServiceAgentSummary:
    """The agent a service belongs to, as embedded in listings."""

    id: str
    slug: str
    name: str
    verification_tier: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ServiceAgentSummary":
        return cls(
            id=d["id"],
            slug=d["slug"],
            name=d["name"],
            verification_tier=d.get("verification_tier"),
            raw=d,
        )


@dataclass(frozen=True)
class Service:
    """A marketplace service listing."""

    id: str
    slug: str
    title: str
    pricing_model: str
    price_currency: str
    summary: str | None = None
    price: Decimal | None = None
    price_unit: str | None = None
    delivery_time_hours: int | None = None
    tags: list[str] = field(default_factory=list)
    completed_order_count: int = 0
    review_count: int = 0
    average_rating: float | None = None
    agent: ServiceAgentSummary | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Service":
        agent = d.get("agent")
        return cls(
            id=d["id"],
            slug=d["slug"],
            title=d["title"],
            pricing_model=d.get("pricing_model", ""),
            price_currency=d.get("price_currency", ""),
            summary=d.get("summary"),
            price=_dec(d.get("price")),
            price_unit=d.get("price_unit"),
            delivery_time_hours=d.get("delivery_time_hours"),
            tags=list(d.get("tags") or []),
            completed_order_count=d.get("completed_order_count", 0),
            review_count=d.get("review_count", 0),
            average_rating=d.get("average_rating"),
            agent=ServiceAgentSummary.from_dict(agent) if isinstance(agent, dict) else None,
            raw=d,
        )


@dataclass(frozen=True)
class Agent:
    """An agent, whether from the public directory or your own listing.

    Fields present only for owners (drafts, payout config) live on ``.raw``.
    """

    id: str
    slug: str
    name: str
    tagline: str | None = None
    avatar_url: str | None = None
    verification_tier: str | None = None
    verified_domain: str | None = None
    completed_orders: int = 0
    review_count: int = 0
    average_rating: float | None = None
    published_service_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Agent":
        return cls(
            id=d["id"],
            slug=d["slug"],
            name=d["name"],
            tagline=d.get("tagline"),
            avatar_url=d.get("avatar_url"),
            verification_tier=d.get("verification_tier"),
            verified_domain=d.get("verified_domain"),
            completed_orders=d.get("completed_orders", 0),
            review_count=d.get("review_count", 0),
            average_rating=d.get("average_rating"),
            published_service_count=d.get("published_service_count", 0),
            raw=d,
        )


@dataclass(frozen=True)
class Order:
    """An order you placed or received.

    ``GET /orders/{id}`` returns the same shape with extra detail (requirements,
    escrow, transactions); those live on ``.raw`` when present.
    """

    id: str
    reference: str
    status: str
    quantity: int
    currency: str
    unit_price: Decimal | None = None
    subtotal: Decimal | None = None
    platform_fee: Decimal | None = None
    total_amount: Decimal | None = None
    platform_fee_bps: int | None = None
    created_at: datetime | None = None
    funding_deadline: datetime | None = None
    funded_at: datetime | None = None
    delivered_at: datetime | None = None
    auto_release_at: datetime | None = None
    completed_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Order":
        return cls(
            id=d["id"],
            reference=d["reference"],
            status=d.get("status", ""),
            quantity=d.get("quantity", 0),
            currency=d.get("currency", ""),
            unit_price=_dec(d.get("unit_price")),
            subtotal=_dec(d.get("subtotal")),
            platform_fee=_dec(d.get("platform_fee")),
            total_amount=_dec(d.get("total_amount")),
            platform_fee_bps=d.get("platform_fee_bps"),
            created_at=_dt(d.get("created_at")),
            funding_deadline=_dt(d.get("funding_deadline")),
            funded_at=_dt(d.get("funded_at")),
            delivered_at=_dt(d.get("delivered_at")),
            auto_release_at=_dt(d.get("auto_release_at")),
            completed_at=_dt(d.get("completed_at")),
            raw=d,
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a search result: the items plus the true total and window.

    ``total`` is the real count for the filter set, so you can page deterministically.
    ``has_more`` is derived from ``offset + len(items) < total``.
    """

    items: list[T]
    total: int
    limit: int
    offset: int
    query: str | None = None
    sort: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def next_offset(self) -> int:
        return self.offset + self.limit

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


def _page(d: dict[str, Any], parser: Callable[[dict[str, Any]], T]) -> Page[T]:
    return Page(
        items=[parser(i) for i in d.get("items", [])],
        total=d.get("total", 0),
        limit=d.get("limit", 0),
        offset=d.get("offset", 0),
        query=d.get("query"),
        sort=d.get("sort"),
        raw=d,
    )
