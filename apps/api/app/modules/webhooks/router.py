"""Webhook management endpoints (authenticated by the browser session)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
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


@router.get("/events", response_model=EventCatalog, summary="Subscribable events")
async def events() -> EventCatalog:
    """The event catalogue. Public, so docs and the create form can render it."""
    return EventCatalog()


@router.get("", response_model=WebhookEndpointList, summary="Your webhook endpoints")
async def list_endpoints(user: CurrentUser, db: DbSession) -> WebhookEndpointList:
    endpoints = await service.list_endpoints(db, user=user)
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
    payload: WebhookEndpointCreate, user: CurrentUser, db: DbSession
) -> WebhookEndpointCreated:
    """Register an endpoint. The signing secret is in the response and shown only
    here, store it to verify delivery signatures."""
    endpoint, secret = await service.create_endpoint(
        db,
        user=user,
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
    endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    await service.revoke_endpoint(db, user=user, endpoint_id=endpoint_id)
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
) -> list[WebhookDeliveryPublic]:
    deliveries = await service.list_deliveries(
        db, user=user, endpoint_id=endpoint_id, limit=limit
    )
    return [WebhookDeliveryPublic.model_validate(d) for d in deliveries]
