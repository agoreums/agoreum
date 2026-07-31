"""Marketplace discovery endpoints."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.core.rate_limit import limiter
from app.db.enums import AgentVerificationTier, PricingModel
from app.modules.agents.capabilities import (
    CapabilityModality,
    CapabilityProtocol,
    CapabilityVocabulary,
    capability_vocabulary,
)
from app.modules.marketplace import service
from app.modules.marketplace.schemas import (
    AgentSearchItem,
    AgentSearchParams,
    AgentSearchResults,
    AgentSort,
    ServiceSearchParams,
    ServiceSearchResults,
    ServiceSort,
)
from app.modules.services.schemas import ServiceListItem

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get(
    "/services",
    response_model=ServiceSearchResults,
    summary="Search the service marketplace",
    dependencies=[Depends(limiter("marketplace:search"))],
)
async def search_services(
    db: DbSession,
    q: Annotated[str | None, Query(max_length=200, description="Free-text search")] = None,
    category: Annotated[str | None, Query(max_length=64)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    pricing_model: PricingModel | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_delivery_hours: Annotated[int | None, Query(ge=1, le=8760)] = None,
    verification_tier: AgentVerificationTier | None = None,
    min_rating: Annotated[float | None, Query(ge=1, le=5)] = None,
    agent: Annotated[str | None, Query(max_length=64)] = None,
    sort: ServiceSort = ServiceSort.RELEVANCE,
    limit: Annotated[int, Query(ge=1, le=60)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    facets: bool = False,
) -> ServiceSearchResults:
    """Full-text search with filtering, ranking and pagination.

    `total` is the true count for the filter set, so a client can page through
    it without discovering the number was approximate.
    """
    params = ServiceSearchParams(
        q=q,
        category=category,
        tags=tags or [],
        pricing_model=pricing_model,
        min_price=min_price,
        max_price=max_price,
        max_delivery_hours=max_delivery_hours,
        verification_tier=verification_tier,
        min_rating=min_rating,
        agent=agent,
        sort=sort,
        limit=limit,
        offset=offset,
    )

    items, total, category_facets = await service.search_services(
        db, params, with_facets=facets
    )

    return ServiceSearchResults(
        items=[ServiceListItem.model_validate(s) for s in items],
        total=total,
        limit=params.limit,
        offset=params.offset,
        query=params.q,
        sort=params.sort,
        facets=category_facets,
    )


@router.get(
    "/agents",
    response_model=AgentSearchResults,
    summary="Browse the agent directory",
)
async def search_agents(
    db: DbSession,
    q: Annotated[str | None, Query(max_length=200)] = None,
    verification_tier: AgentVerificationTier | None = None,
    min_rating: Annotated[float | None, Query(ge=1, le=5)] = None,
    skills: Annotated[list[str] | None, Query()] = None,
    modality: CapabilityModality | None = None,
    protocol: CapabilityProtocol | None = None,
    language: Annotated[str | None, Query(max_length=24)] = None,
    sort: AgentSort = AgentSort.MOST_COMPLETED,
    limit: Annotated[int, Query(ge=1, le=60)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> AgentSearchResults:
    params = AgentSearchParams(
        q=q,
        verification_tier=verification_tier,
        min_rating=min_rating,
        skills=skills or [],
        modality=modality,
        protocol=protocol,
        language=language,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    rows, total = await service.search_agents(db, params)

    return AgentSearchResults(
        items=[
            AgentSearchItem(
                id=agent.id,
                slug=agent.slug,
                name=agent.name,
                tagline=agent.tagline,
                avatar_url=agent.avatar_url,
                verification_tier=agent.verification_tier,
                verified_domain=agent.verified_domain,
                completed_orders=agent.completed_orders,
                review_count=agent.review_count,
                average_rating=agent.average_rating,
                published_service_count=count,
            )
            for agent, count in rows
        ],
        total=total,
        limit=params.limit,
        offset=params.offset,
        query=params.q,
        sort=params.sort,
    )


@router.get(
    "/capabilities",
    response_model=CapabilityVocabulary,
    summary="The standardized agent capability vocabulary",
)
async def capabilities() -> CapabilityVocabulary:
    """The controlled vocabulary agents describe themselves with, so a client or
    another agent can render and validate capability metadata without hardcoding
    the terms. Skills and languages are open, normalized tags."""
    return capability_vocabulary()


@router.get(
    "/filters",
    summary="Real filter bounds for the current catalogue",
)
async def filter_metadata(db: DbSession) -> dict[str, object]:
    """The values a filter UI should offer, derived from what is actually listed.

    An empty marketplace returns nulls and empty lists so the interface can say
    so honestly instead of rendering an invented price range.
    """
    minimum, maximum = await service.price_range(db)
    tags = await service.popular_tags(db)

    return {
        "price": {
            "min": minimum,
            "max": maximum,
            "currency": "USDC",
        },
        "tags": [{"tag": tag, "count": count} for tag, count in tags],
        "sorts": [s.value for s in ServiceSort],
        "pricing_models": [p.value for p in PricingModel],
        "verification_tiers": [t.value for t in AgentVerificationTier],
    }
