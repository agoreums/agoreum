"""Request and response models for notifications."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.enums import NotificationCategory, NotificationChannel


class DeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: NotificationChannel
    status: str
    sent_at: datetime | None
    failed_at: datetime | None
    # Present when a delivery was suppressed or failed, so the reason is
    # visible rather than the message silently never arriving.
    last_error: str | None


class NotificationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: NotificationCategory
    event_type: str
    title: str
    body: str | None
    action_url: str | None
    payload: dict | None
    related_order_id: uuid.UUID | None
    related_agent_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime
    deliveries: list[DeliverySummary] = []


class NotificationList(BaseModel):
    items: list[NotificationPublic]
    total: int
    unread: int
    limit: int
    offset: int


class PreferenceUpdate(BaseModel):
    category: NotificationCategory
    channel: NotificationChannel
    enabled: bool


class PreferencePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: NotificationCategory
    channel: NotificationChannel
    enabled: bool


class EmailStatus(BaseModel):
    """Whether outbound email would actually be sent from this deployment.

    Surfaced so nobody has to guess why a message did not arrive.
    """

    enabled: bool
    reason: str | None
    from_address: str
