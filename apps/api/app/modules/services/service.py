"""Service catalogue: publishing and lifecycle."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.enums import AgentStatus, ServiceStatus
from app.modules.agents.models import Agent
from app.modules.services.models import Category, Service
from app.modules.services.schemas import ServiceCreate, ServiceUpdate

logger = get_logger(__name__)

MAX_SERVICES_PER_AGENT = 50


# --- Categories -------------------------------------------------------------


async def list_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .options(selectinload(Category.children))
        .order_by(Category.sort_order, Category.name)
    )
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: uuid.UUID) -> Category | None:
    return (
        await db.execute(select(Category).where(Category.id == category_id))
    ).scalar_one_or_none()


# --- Reads ------------------------------------------------------------------


async def get_by_slug(
    db: AsyncSession, *, agent_slug: str, service_slug: str
) -> Service | None:
    """Load a service by its agent and slug, with the joins a detail page needs."""
    result = await db.execute(
        select(Service)
        .join(Agent, Agent.id == Service.agent_id)
        .where(Agent.slug == agent_slug.lower(), Service.slug == service_slug.lower())
        .options(selectinload(Service.agent), selectinload(Service.category))
    )
    return result.scalar_one_or_none()


async def require_service(
    db: AsyncSession, *, agent_slug: str, service_slug: str
) -> Service:
    service = await get_by_slug(db, agent_slug=agent_slug, service_slug=service_slug)
    if service is None:
        raise NotFoundError("No such service.")
    return service


async def list_for_agent(
    db: AsyncSession, *, agent_id: uuid.UUID, include_unpublished: bool = False
) -> list[Service]:
    stmt = select(Service).where(Service.agent_id == agent_id)
    if not include_unpublished:
        stmt = stmt.where(Service.status == ServiceStatus.PUBLISHED)
    stmt = stmt.options(
        selectinload(Service.agent), selectinload(Service.category)
    ).order_by(Service.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


# --- Writes -----------------------------------------------------------------


async def create_service(
    db: AsyncSession, *, agent: Agent, payload: ServiceCreate
) -> Service:
    """Create a service under an agent. Starts as a draft."""
    if agent.status == AgentStatus.SUSPENDED:
        raise ConflictError(
            "This agent is suspended and cannot publish services.",
            code="agent_suspended",
        )
    if agent.status == AgentStatus.RETIRED:
        raise ConflictError(
            "This agent has been retired.", code="agent_retired"
        )

    count = (
        await db.execute(
            select(func.count())
            .select_from(Service)
            .where(
                Service.agent_id == agent.id,
                Service.status != ServiceStatus.ARCHIVED,
            )
        )
    ).scalar_one()
    if count >= MAX_SERVICES_PER_AGENT:
        raise ConflictError(
            f"This agent has reached the limit of {MAX_SERVICES_PER_AGENT} services.",
            code="service_limit_reached",
        )

    if payload.category_id is not None:
        category = await get_category(db, payload.category_id)
        if category is None or not category.is_active:
            raise NotFoundError("No such category.")

    service = Service(
        agent_id=agent.id,
        status=ServiceStatus.DRAFT,
        **payload.model_dump(),
    )
    db.add(service)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "This agent already has a service with that name.",
            code="service_slug_taken",
        ) from exc

    # The search vector is maintained by a database trigger, so it is already
    # correct here without any application-side indexing step.
    await db.refresh(service)
    logger.info(
        "service_created",
        extra={"service_id": str(service.id), "agent_id": str(agent.id)},
    )
    return service


async def update_service(
    db: AsyncSession, *, service: Service, payload: ServiceUpdate
) -> Service:
    changes = payload.model_dump(exclude_unset=True)

    if "category_id" in changes and changes["category_id"] is not None:
        category = await get_category(db, changes["category_id"])
        if category is None or not category.is_active:
            raise NotFoundError("No such category.")

    for field, value in changes.items():
        setattr(service, field, value)

    _validate_pricing_coherence(service)

    await db.flush()
    await db.refresh(service)
    return service


def _validate_pricing_coherence(service: Service) -> None:
    """Re-check pricing after a partial update.

    A patch that changes only `pricing_model` can leave the record inconsistent
    with fields it did not touch, which the database would reject with an opaque
    constraint error. Checking here produces a message the caller can act on.
    """
    from app.db.enums import PricingModel

    if service.pricing_model != PricingModel.NEGOTIATED and service.price is None:
        raise ConflictError(
            "A price is required unless the pricing model is 'negotiated'.",
            code="price_required",
        )
    if service.pricing_model == PricingModel.PER_UNIT and not service.price_unit:
        raise ConflictError(
            "Per-unit pricing needs a unit, for example '1000 tokens'.",
            code="price_unit_required",
        )
    if service.max_quantity is not None and service.max_quantity < service.min_quantity:
        raise ConflictError(
            "Maximum quantity cannot be below the minimum.",
            code="quantity_range_invalid",
        )


async def publish_service(
    db: AsyncSession, *, service: Service, agent: Agent
) -> Service:
    """Make a service orderable.

    Gated on the provider being able to receive payment. Publishing a service
    whose agent has no verified payout wallet would advertise work that cannot
    be settled.
    """
    if service.status == ServiceStatus.PUBLISHED:
        return service

    if service.status == ServiceStatus.SUSPENDED:
        raise ConflictError(
            "This service is suspended.", code="service_suspended"
        )

    if agent.status != AgentStatus.ACTIVE:
        raise ConflictError(
            "Publish the agent before publishing its services.",
            code="agent_not_published",
        )

    if agent.payout_wallet_id is None:
        raise ConflictError(
            "This agent has no verified payout wallet, so it cannot be paid.",
            code="payout_wallet_required",
        )

    _validate_pricing_coherence(service)

    service.status = ServiceStatus.PUBLISHED
    service.published_at = service.published_at or datetime.now(UTC)
    await db.flush()
    await db.refresh(service)

    logger.info("service_published", extra={"service_id": str(service.id)})
    return service


async def set_availability(
    db: AsyncSession, *, service: Service, available: bool
) -> Service:
    """Temporarily stop or resume taking new orders.

    Orders already in flight are unaffected: withdrawing availability is about
    intake, not about abandoning committed work.
    """
    if service.status == ServiceStatus.SUSPENDED:
        raise ConflictError("This service is suspended.", code="service_suspended")

    if available:
        if service.status == ServiceStatus.UNAVAILABLE:
            service.status = ServiceStatus.PUBLISHED
    elif service.status == ServiceStatus.PUBLISHED:
        service.status = ServiceStatus.UNAVAILABLE

    await db.flush()
    await db.refresh(service)
    return service


async def archive_service(db: AsyncSession, *, service: Service) -> Service:
    """Withdraw a service permanently, keeping it readable for order history."""
    service.status = ServiceStatus.ARCHIVED
    await db.flush()
    await db.refresh(service)
    logger.info("service_archived", extra={"service_id": str(service.id)})
    return service


def is_visible_to(service: Service, *, viewer_id: uuid.UUID | None) -> bool:
    """Whether a viewer may see this service at all.

    Drafts and archived services are owner-only. This is used to return 404
    rather than 403, so unpublished work is not disclosed by its absence.
    """
    if service.status in {
        ServiceStatus.PUBLISHED,
        ServiceStatus.UNAVAILABLE,
    }:
        return True
    if viewer_id is None:
        return False
    return service.agent.owner_id == viewer_id
