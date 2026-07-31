"""Marketplace discovery: search, filtering, and ranking.

Search runs against `services.search_vector`, a tsvector maintained by a database
trigger and backed by a GIN index. Queries are parsed with `websearch_to_tsquery`
rather than `to_tsquery`: it accepts what people actually type, quoted phrases,
`or`, leading `-` to exclude, and, critically, never raises on malformed input.
`to_tsquery` would turn a stray parenthesis into a 500.

All filtering happens in SQL. Nothing is fetched and then discarded in Python,
because that would make `total` a lie and pagination incoherent.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.enums import AgentStatus, AgentVerificationTier, ServiceStatus
from app.db.search import SEARCH_CONFIG
from app.modules.agents.models import Agent
from app.modules.marketplace.schemas import (
    AgentSearchParams,
    AgentSort,
    CategoryFacet,
    ServiceSearchParams,
    ServiceSort,
)
from app.modules.services.models import Category, Service

logger = get_logger(__name__)

# Verification tiers ordered by how much has actually been proven, so a filter
# for "domain verified" also admits anything stronger.
TIER_RANK: dict[AgentVerificationTier, int] = {
    AgentVerificationTier.UNVERIFIED: 0,
    AgentVerificationTier.DOMAIN_VERIFIED: 1,
    AgentVerificationTier.ORGANIZATION_VERIFIED: 2,
}

# Statuses that mean a service is on the marketplace at all. UNAVAILABLE is
# included: the provider has paused intake, but the listing is still real and
# hiding it would make a bookmarked page 404.
DISCOVERABLE_SERVICE_STATUSES = (
    ServiceStatus.PUBLISHED,
    ServiceStatus.UNAVAILABLE,
)


def _tsquery(text: str):
    return func.websearch_to_tsquery(SEARCH_CONFIG, text)


def _average_rating_expr(review_count, rating_sum):
    """Mean rating in SQL, or NULL when there are no reviews.

    NULL rather than 0 matters for sorting: an unrated provider must not be
    ranked below a genuinely poor one.
    """
    return func.nullif(
        func.coalesce(rating_sum, 0) * 1.0 / func.nullif(review_count, 0), None
    )


def _apply_service_filters(
    stmt: Select, params: ServiceSearchParams, *, category_id_map: dict[str, object]
) -> Select:
    """Apply every filter to a statement. Shared by the results and count queries
    so the total can never disagree with the page."""
    stmt = stmt.where(
        Service.status.in_(DISCOVERABLE_SERVICE_STATUSES),
        # A service is only discoverable while its provider is active. A paused
        # or retired agent's listings must not appear as though orderable.
        Agent.status == AgentStatus.ACTIVE,
    )

    if params.q:
        stmt = stmt.where(Service.search_vector.op("@@")(_tsquery(params.q)))

    if params.category:
        category_id = category_id_map.get(params.category)
        if category_id is None:
            # An unknown category yields nothing, rather than being ignored and
            # silently returning the whole catalogue.
            stmt = stmt.where(false())
        else:
            child_ids = category_id_map.get(f"__children__{params.category}", [])
            stmt = stmt.where(Service.category_id.in_([category_id, *child_ids]))

    if params.tags:
        # Overlap: a service matches if it carries any of the requested tags.
        stmt = stmt.where(Service.tags.op("&&")(params.tags))

    if params.pricing_model:
        stmt = stmt.where(Service.pricing_model == params.pricing_model)

    if params.min_price is not None:
        stmt = stmt.where(Service.price >= params.min_price)

    if params.max_price is not None:
        stmt = stmt.where(Service.price <= params.max_price)

    if params.max_delivery_hours is not None:
        stmt = stmt.where(
            and_(
                Service.delivery_time_hours.isnot(None),
                Service.delivery_time_hours <= params.max_delivery_hours,
            )
        )

    if params.verification_tier:
        wanted = TIER_RANK[params.verification_tier]
        acceptable = [tier for tier, rank in TIER_RANK.items() if rank >= wanted]
        stmt = stmt.where(Agent.verification_tier.in_(acceptable))

    if params.min_rating is not None:
        # Requires real reviews: an unrated agent cannot satisfy a rating floor.
        stmt = stmt.where(
            and_(
                Agent.review_count > 0,
                Agent.rating_sum * 1.0 / Agent.review_count >= params.min_rating,
            )
        )

    if params.agent:
        stmt = stmt.where(Agent.slug == params.agent.lower())

    return stmt


def _apply_service_sort(stmt: Select, params: ServiceSearchParams) -> Select:
    sort = params.sort

    # Relevance is only real when something was searched for. Without a query
    # there is nothing to rank, so fall back to genuine activity.
    if sort == ServiceSort.RELEVANCE and not params.q:
        sort = ServiceSort.MOST_COMPLETED

    if sort == ServiceSort.RELEVANCE:
        rank = func.ts_rank_cd(Service.search_vector, _tsquery(params.q))
        return stmt.order_by(
            rank.desc(),
            Service.completed_order_count.desc(),
            Service.id,
        )

    if sort == ServiceSort.NEWEST:
        return stmt.order_by(Service.published_at.desc().nullslast(), Service.id)

    if sort == ServiceSort.PRICE_LOW:
        # Negotiated services have no price; they sort last rather than first.
        return stmt.order_by(Service.price.asc().nullslast(), Service.id)

    if sort == ServiceSort.PRICE_HIGH:
        return stmt.order_by(Service.price.desc().nullslast(), Service.id)

    if sort == ServiceSort.TOP_RATED:
        rating = _average_rating_expr(Service.review_count, Service.rating_sum)
        return stmt.order_by(
            rating.desc().nullslast(),
            Service.review_count.desc(),
            Service.id,
        )

    return stmt.order_by(
        Service.completed_order_count.desc(),
        Service.published_at.desc().nullslast(),
        Service.id,
    )


async def _category_id_map(db: AsyncSession) -> dict[str, object]:
    """Resolve category slugs to ids, including each parent's children.

    Filtering by a parent category should return everything beneath it; a user
    picking "Software & Engineering" expects code review results.
    """
    rows = (
        await db.execute(select(Category.id, Category.slug, Category.parent_id))
    ).all()

    by_id = {row.id: row.slug for row in rows}
    mapping: dict[str, object] = {row.slug: row.id for row in rows}

    children: dict[str, list] = {}
    for row in rows:
        if row.parent_id is not None:
            parent_slug = by_id.get(row.parent_id)
            if parent_slug:
                children.setdefault(parent_slug, []).append(row.id)

    for parent_slug, ids in children.items():
        mapping[f"__children__{parent_slug}"] = ids

    return mapping


async def search_services(
    db: AsyncSession, params: ServiceSearchParams, *, with_facets: bool = False
) -> tuple[list[Service], int, list[CategoryFacet] | None]:
    """Run a marketplace search.

    Returns the page, the true total for the filter set, and optionally category
    facet counts drawn from the same filters.
    """
    category_map = await _category_id_map(db)

    base = select(Service).join(Agent, Agent.id == Service.agent_id)
    filtered = _apply_service_filters(base, params, category_id_map=category_map)

    total = (
        await db.execute(
            select(func.count()).select_from(filtered.subquery())
        )
    ).scalar_one()

    page_stmt = _apply_service_sort(filtered, params).options(
        selectinload(Service.agent), selectinload(Service.category)
    )
    page_stmt = page_stmt.limit(params.limit).offset(params.offset)

    items = list((await db.execute(page_stmt)).scalars().all())

    facets = None
    if with_facets:
        facets = await _category_facets(db, params, category_map)

    logger.info(
        "marketplace_search",
        extra={
            "has_query": bool(params.q),
            "result_total": total,
            "sort": params.sort.value,
        },
    )
    return items, total, facets


async def _category_facets(
    db: AsyncSession, params: ServiceSearchParams, category_map: dict[str, object]
) -> list[CategoryFacet]:
    """Count results per category under the current filters, ignoring the
    category filter itself so the user can see where else results exist."""
    unfiltered_by_category = params.model_copy(update={"category": None})

    stmt = (
        select(Category.slug, Category.name, func.count(Service.id).label("count"))
        .select_from(Service)
        .join(Agent, Agent.id == Service.agent_id)
        .join(Category, Category.id == Service.category_id)
    )
    stmt = _apply_service_filters(
        stmt, unfiltered_by_category, category_id_map=category_map
    )
    stmt = stmt.group_by(Category.slug, Category.name).order_by(
        func.count(Service.id).desc()
    )

    rows = (await db.execute(stmt)).all()
    return [
        CategoryFacet(slug=row.slug, name=row.name, count=row.count) for row in rows
    ]


async def search_agents(
    db: AsyncSession, params: AgentSearchParams
) -> tuple[list[tuple[Agent, int]], int]:
    """Search the agent directory.

    Agents have no tsvector of their own, so text matching is a prefix/substring
    search over name, slug and tagline. That is honest about what it does rather
    than claiming full-text relevance it cannot deliver.
    """
    published_services = (
        select(func.count(Service.id))
        .where(
            Service.agent_id == Agent.id,
            Service.status.in_(DISCOVERABLE_SERVICE_STATUSES),
        )
        .correlate(Agent)
        .scalar_subquery()
    )

    stmt = select(Agent, published_services.label("published_service_count")).where(
        Agent.status == AgentStatus.ACTIVE
    )

    if params.q:
        pattern = f"%{params.q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Agent.name).like(pattern),
                Agent.slug.like(pattern),
                func.lower(func.coalesce(Agent.tagline, "")).like(pattern),
            )
        )

    if params.verification_tier:
        wanted = TIER_RANK[params.verification_tier]
        acceptable = [tier for tier, rank in TIER_RANK.items() if rank >= wanted]
        stmt = stmt.where(Agent.verification_tier.in_(acceptable))

    if params.min_rating is not None:
        stmt = stmt.where(
            and_(
                Agent.review_count > 0,
                Agent.rating_sum * 1.0 / Agent.review_count >= params.min_rating,
            )
        )

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    if params.sort == AgentSort.NEWEST:
        stmt = stmt.order_by(Agent.published_at.desc().nullslast(), Agent.id)
    elif params.sort == AgentSort.TOP_RATED:
        rating = _average_rating_expr(Agent.review_count, Agent.rating_sum)
        stmt = stmt.order_by(
            rating.desc().nullslast(), Agent.review_count.desc(), Agent.id
        )
    else:
        stmt = stmt.order_by(
            Agent.completed_orders.desc(),
            Agent.published_at.desc().nullslast(),
            Agent.id,
        )

    rows = (await db.execute(stmt.limit(params.limit).offset(params.offset))).all()
    return [(row[0], row[1]) for row in rows], total


async def price_range(db: AsyncSession) -> tuple[Decimal | None, Decimal | None]:
    """The real minimum and maximum price on the marketplace.

    Returns (None, None) when nothing is listed, so a client can hide a price
    filter rather than render an invented range.
    """
    row = (
        await db.execute(
            select(func.min(Service.price), func.max(Service.price))
            .select_from(Service)
            .join(Agent, Agent.id == Service.agent_id)
            .where(
                Service.status.in_(DISCOVERABLE_SERVICE_STATUSES),
                Agent.status == AgentStatus.ACTIVE,
                Service.price.isnot(None),
            )
        )
    ).one()
    return row[0], row[1]


async def popular_tags(db: AsyncSession, *, limit: int = 20) -> list[tuple[str, int]]:
    """Tags actually in use, with real counts. Empty when nothing is listed."""
    tag = func.unnest(Service.tags).label("tag")
    subquery = (
        select(tag)
        .select_from(Service)
        .join(Agent, Agent.id == Service.agent_id)
        .where(
            Service.status.in_(DISCOVERABLE_SERVICE_STATUSES),
            Agent.status == AgentStatus.ACTIVE,
        )
        .subquery()
    )

    rows = (
        await db.execute(
            select(subquery.c.tag, func.count().label("count"))
            .group_by(subquery.c.tag)
            .order_by(func.count().desc(), subquery.c.tag)
            .limit(limit)
        )
    ).all()
    return [(row.tag, row.count) for row in rows]
