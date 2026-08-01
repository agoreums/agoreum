"""Service catalogue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.errors import NotFoundError
from app.core.rate_limit import limiter
from app.modules.agents import service as agent_service
from app.modules.organizations.authz import is_member
from app.modules.services import service as catalogue
from app.modules.services.schemas import (
    CategorySummary,
    CategoryTree,
    ServiceCreate,
    ServiceDetail,
    ServiceOwnerView,
    ServiceUpdate,
)

router = APIRouter(tags=["services"])


@router.get(
    "/categories",
    response_model=list[CategoryTree],
    summary="The marketplace category tree",
)
async def list_categories(db: DbSession) -> list[CategoryTree]:
    categories = await catalogue.list_categories(db)
    roots = [c for c in categories if c.parent_id is None]
    return [
        CategoryTree(
            **CategorySummary.model_validate(root).model_dump(),
            children=[
                CategorySummary.model_validate(child)
                for child in sorted(root.children, key=lambda c: c.sort_order)
                if child.is_active
            ],
        )
        for root in roots
    ]


@router.get(
    "/agents/{agent_slug}/services",
    response_model=list[ServiceDetail],
    summary="Services offered by an agent",
)
async def list_agent_services(
    agent_slug: str, db: DbSession, user: OptionalUser
) -> list[ServiceDetail]:
    agent = await agent_service.require_agent(db, agent_slug)

    # The owner sees drafts and archived services; everyone else sees only what
    # is actually on offer.
    is_owner = user is not None and await is_member(
        db, org_id=agent.org_id, user_id=user.id
    )
    services = await catalogue.list_for_agent(
        db, agent_id=agent.id, include_unpublished=is_owner
    )
    return [ServiceDetail.model_validate(s) for s in services]


@router.post(
    "/agents/{agent_slug}/services",
    response_model=ServiceOwnerView,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new service",
    dependencies=[Depends(limiter("services:create"))],
)
async def create_service(
    agent_slug: str, payload: ServiceCreate, user: CurrentUser, db: DbSession
) -> ServiceOwnerView:
    agent = await agent_service.require_managed_agent(db, agent_slug, user=user)
    created = await catalogue.create_service(db, agent=agent, payload=payload)
    return ServiceOwnerView.model_validate(created)


@router.get(
    "/agents/{agent_slug}/services/{service_slug}",
    response_model=ServiceDetail,
    summary="A service's public page",
)
async def get_service(
    agent_slug: str, service_slug: str, db: DbSession, user: OptionalUser
) -> ServiceDetail:
    svc = await catalogue.require_service(
        db, agent_slug=agent_slug, service_slug=service_slug
    )
    if not await catalogue.is_visible_to(
        db, svc, viewer_id=user.id if user else None
    ):
        raise NotFoundError("No such service.")
    return ServiceDetail.model_validate(svc)


@router.patch(
    "/agents/{agent_slug}/services/{service_slug}",
    response_model=ServiceOwnerView,
    summary="Update a service",
)
async def update_service(
    agent_slug: str,
    service_slug: str,
    payload: ServiceUpdate,
    user: CurrentUser,
    db: DbSession,
) -> ServiceOwnerView:
    await agent_service.require_managed_agent(db, agent_slug, user=user)
    svc = await catalogue.require_service(
        db, agent_slug=agent_slug, service_slug=service_slug
    )
    return ServiceOwnerView.model_validate(
        await catalogue.update_service(db, service=svc, payload=payload)
    )


@router.post(
    "/agents/{agent_slug}/services/{service_slug}/publish",
    response_model=ServiceOwnerView,
    summary="Make a service orderable",
)
async def publish_service(
    agent_slug: str, service_slug: str, user: CurrentUser, db: DbSession
) -> ServiceOwnerView:
    agent = await agent_service.require_managed_agent(db, agent_slug, user=user)
    svc = await catalogue.require_service(
        db, agent_slug=agent_slug, service_slug=service_slug
    )
    return ServiceOwnerView.model_validate(
        await catalogue.publish_service(db, service=svc, agent=agent)
    )


@router.post(
    "/agents/{agent_slug}/services/{service_slug}/availability",
    response_model=ServiceOwnerView,
    summary="Pause or resume taking new orders",
)
async def set_availability(
    agent_slug: str,
    service_slug: str,
    available: bool,
    user: CurrentUser,
    db: DbSession,
) -> ServiceOwnerView:
    await agent_service.require_managed_agent(db, agent_slug, user=user)
    svc = await catalogue.require_service(
        db, agent_slug=agent_slug, service_slug=service_slug
    )
    return ServiceOwnerView.model_validate(
        await catalogue.set_availability(db, service=svc, available=available)
    )


@router.delete(
    "/agents/{agent_slug}/services/{service_slug}",
    response_model=ServiceOwnerView,
    summary="Withdraw a service",
)
async def archive_service(
    agent_slug: str, service_slug: str, user: CurrentUser, db: DbSession
) -> ServiceOwnerView:
    """Archives rather than deletes: order history references this record."""
    await agent_service.require_managed_agent(db, agent_slug, user=user)
    svc = await catalogue.require_service(
        db, agent_slug=agent_slug, service_slug=service_slug
    )
    return ServiceOwnerView.model_validate(
        await catalogue.archive_service(db, service=svc)
    )
