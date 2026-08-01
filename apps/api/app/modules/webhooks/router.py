"""Webhook management endpoints (authenticated by the browser session)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.modules.organizations import service as org_service
from app.modules.organizations.authz import OrgAction
from app.modules.webhooks import service
from app.modules.webhooks.schemas import (
    EventCatalog,
    WebhookDeliveryPublic,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointList,
    WebhookEndpointPublic,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Webhook endpoints belong to an organization. The `org` query parameter selects
# which one; omitted, it is the caller's personal organization. Managing endpoints
# requires the keys role.
OrgSlug = Annotated[str | None, Query(alias="org", max_length=64)]


@router.get("/events", response_model=EventCatalog, summary="Subscribable events")
async def events() -> EventCatalog:
    """The event catalogue. Public, so docs and the create form can render it."""
    return EventCatalog()


@router.get(
    "", response_model=WebhookEndpointList, summary="An organization's webhook endpoints"
)
async def list_endpoints(
    user: CurrentUser, db: DbSession, org: OrgSlug = None
) -> WebhookEndpointList:
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    endpoints = await service.list_endpoints(db, org=organization)
    return WebhookEndpointList(
        items=[WebhookEndpointPublic.model_validate(e) for e in endpoints],
        total=len(endpoints),
    )


@router.post(
    "",
    response_model=WebhookEndpointCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Register a webhook endpoint",
)
async def create_endpoint(
    payload: WebhookEndpointCreate,
    user: CurrentUser,
    db: DbSession,
    org: OrgSlug = None,
) -> WebhookEndpointCreated:
    """Register an endpoint. The signing secret is in the response and shown only
    here, store it to verify delivery signatures."""
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    endpoint, secret = await service.create_endpoint(
        db,
        org=organization,
        creator=user,
        url=payload.url,
        events=payload.events,
        description=payload.description,
    )
    public = WebhookEndpointPublic.model_validate(endpoint)
    return WebhookEndpointCreated(**public.model_dump(), secret=secret)


@router.delete(
    "/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a webhook endpoint",
)
async def revoke_endpoint(
    endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession, org: OrgSlug = None
) -> Response:
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    await service.revoke_endpoint(db, org=organization, endpoint_id=endpoint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{endpoint_id}/deliveries",
    response_model=list[WebhookDeliveryPublic],
    summary="Recent deliveries for an endpoint",
)
async def list_deliveries(
    endpoint_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    org: OrgSlug = None,
) -> list[WebhookDeliveryPublic]:
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    deliveries = await service.list_deliveries(
        db, org=organization, endpoint_id=endpoint_id, limit=limit
    )
    return [WebhookDeliveryPublic.model_validate(d) for d in deliveries]
