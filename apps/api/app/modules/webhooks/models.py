"""Webhook endpoint and delivery models.

A *WebhookEndpoint* is a URL a user registers to receive event notifications, with
a signing secret and a set of subscribed events. A *WebhookDelivery* is one attempt
to send one event to one endpoint, an outbox row the delivery worker drains, so
sending never happens in the request that raised the event and a transient failure
is retried rather than lost.

The signing secret is stored so the worker can sign each payload; it is not an
access credential (it only lets the receiver verify a payload is genuinely from us),
and it is shown to the owner once at creation, like an API key.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import WebhookDeliveryStatus, pg_enum

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization


class WebhookEndpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "webhook_endpoints"

    # An endpoint belongs to an organization; every member's events flow to it.
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Who registered it, for audit. Kept even if that user later leaves the org.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # The HMAC signing secret. Retained (not hashed) because the worker must sign
    # every payload with it and the receiver verifies with the same value.
    secret: Mapped[str] = mapped_column(String(80), nullable=False)

    # Subscribed event types, or ["*"] for all. Validated in the application.
    events: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)

    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship()
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_webhook_endpoints_org_id", "org_id"),)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __repr__(self) -> str:
        return f"<WebhookEndpoint {self.id} {self.url}>"


class WebhookDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # A stable id for the logical event, sent as a header so a receiver can
    # deduplicate retries of the same delivery.
    event_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, server_default=func.gen_random_uuid()
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        pg_enum(WebhookDeliveryStatus, "webhook_delivery_status"),
        nullable=False,
        default=WebhookDeliveryStatus.PENDING,
        server_default=WebhookDeliveryStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    # When the worker should next try. Indexed so the worker's claim query is cheap.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Response latency of the last attempt, in milliseconds, for the health view.
    last_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="deliveries")

    __table_args__ = (
        Index("ix_webhook_deliveries_endpoint_id", "endpoint_id"),
        # The worker claims due work with: status in (pending, failed)
        # AND next_attempt_at <= now(). A partial index keeps that scan tiny even
        # as succeeded/exhausted rows accumulate.
        Index(
            "ix_webhook_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status in ('pending', 'failed')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<WebhookDelivery {self.id} {self.event_type} {self.status}>"
