"""Request and response models for webhooks."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.webhooks.events import EVENTS


class WebhookEndpointCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    # Event types to subscribe to, or ["*"] for all.
    events: list[str] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=100)


class WebhookEndpointPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    description: str | None
    events: list[str]
    last_delivery_at: datetime | None
    last_success_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class WebhookEndpointCreated(WebhookEndpointPublic):
    """Returned once at creation; carries the signing secret, shown only here."""

    secret: str


class WebhookEndpointList(BaseModel):
    items: list[WebhookEndpointPublic]
    total: int


class WebhookDeliveryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    event_id: uuid.UUID
    status: str
    attempts: int
    max_attempts: int
    last_status_code: int | None
    last_error: str | None
    last_duration_ms: int | None
    next_attempt_at: datetime
    delivered_at: datetime | None
    created_at: datetime


class EventInfo(BaseModel):
    event: str
    description: str


class EventCatalog(BaseModel):
    """The events a webhook may subscribe to, for the docs and the create UI."""

    events: list[EventInfo] = [
        EventInfo(event=e, description=d) for e, d in EVENTS.items()
    ]
