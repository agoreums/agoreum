"""Notification models.

Notifications are stored once and delivered across one or more channels. Delivery
per channel is tracked separately from the notification itself, because an in-app
notification can succeed while its email fails, and the system must be able to
report that accurately rather than showing a single misleading "sent" flag.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import (
    NotificationCategory,
    NotificationChannel,
    NotificationDeliveryStatus,
    pg_enum,
)
from app.db.types import LowercaseString

if TYPE_CHECKING:
    from app.modules.users.models import User


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single notification addressed to a user."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[NotificationCategory] = mapped_column(
        pg_enum(NotificationCategory, "notification_category"),
        nullable=False,
    )
    # Specific event, e.g. "order.delivered". Drives template selection and lets
    # clients handle types they know without parsing prose.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # Rendered in the recipient's locale at creation time.
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="en"
    )

    # Structured payload (order reference, amounts, ids) for client-side rendering.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Loose references: a notification outlives the entity it describes.
    related_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    related_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="notifications")
    deliveries: Mapped[list[NotificationDelivery]] = relationship(
        back_populates="notification", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        # Powers the unread badge and the inbox query without a sequential scan.
        Index(
            "ix_notifications_user_unread",
            "user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL AND archived_at IS NULL"),
        ),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_related_order_id", "related_order_id"),
    )

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __repr__(self) -> str:
        return f"<Notification {self.event_type} user={self.user_id}>"


class NotificationDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One delivery attempt of a notification over one channel.

    Failures are recorded, not swallowed. `SUPPRESSED` distinguishes "the user asked
    not to receive this" from "we tried and it failed", which matters when
    diagnosing why someone did not hear about a payment.
    """

    __tablename__ = "notification_deliveries"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        pg_enum(NotificationChannel, "notification_channel"),
        nullable=False,
    )
    status: Mapped[NotificationDeliveryStatus] = mapped_column(
        pg_enum(NotificationDeliveryStatus, "notification_delivery_status"),
        nullable=False,
        default=NotificationDeliveryStatus.PENDING,
        server_default=NotificationDeliveryStatus.PENDING.value,
    )

    # Where it went, an email address for the email channel. NULL for in-app.
    destination: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Provider-side id (e.g. the Resend message id) for reconciling with webhooks.
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notification: Mapped[Notification] = relationship(back_populates="deliveries")

    __table_args__ = (
        # One delivery row per notification per channel.
        UniqueConstraint("notification_id", "channel", name="notification_channel"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint(
            "(status = 'failed') = (failed_at IS NOT NULL)",
            name="failed_at_matches_status",
        ),
        # Anything past 'sent' must record when it was sent.
        CheckConstraint(
            "status NOT IN ('sent', 'delivered') OR sent_at IS NOT NULL",
            name="sent_states_require_sent_at",
        ),
        # Email that goes anywhere must record where. A suppressed row is the
        # exception, because it is the record of a message that deliberately went
        # nowhere: the recipient has no address, has not proven the one they
        # gave, or bounced. Requiring a destination there forced the code to
        # either invent one or refuse to write the row at all, and the second is
        # what happened: the insert violated this constraint and took sign-in
        # down with a 503 for every account without an email.
        CheckConstraint(
            "channel <> 'email' OR destination IS NOT NULL "
            "OR status = 'suppressed'",
            name="email_requires_destination",
        ),
        Index("ix_notification_deliveries_notification_id", "notification_id"),
        # Drives the retry worker.
        Index(
            "ix_notification_deliveries_retry_due",
            "next_retry_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_notification_deliveries_provider_message_id", "provider_message_id"),
    )

    def __repr__(self) -> str:
        return f"<NotificationDelivery {self.channel} {self.status}>"


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-user, per-category, per-channel delivery preference.

    Absence of a row means the platform default applies. Security notifications are
    deliberately not suppressible, that is enforced in the service layer, since a
    user must always learn about a new sign-in or a payout address change.
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[NotificationCategory] = mapped_column(
        # create_type=False: this enum type is created by the Notification table
        # above; declaring it again here would emit a duplicate CREATE TYPE.
        pg_enum(NotificationCategory, "notification_category", create_type=False),
        nullable=False,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        pg_enum(NotificationChannel, "notification_channel", create_type=False),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    user: Mapped[User] = relationship(back_populates="notification_preferences")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "category", "channel", name="user_category_channel"
        ),
        Index("ix_notification_preferences_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<NotificationPreference {self.category}/{self.channel}={self.enabled}>"


class EmailSuppression(Base, UUIDPrimaryKeyMixin):
    """An address the platform must stop mailing.

    Sending to an address that has hard bounced, or whose owner marked a previous
    message as spam, is how a domain's sending reputation is destroyed. Providers
    treat repeat sends to known-bad addresses as the clearest signal of a sender
    who is not paying attention, and the damage lands on every later message,
    including the security notices that most need to arrive.

    A complaint is also a person saying they do not want this. Honouring that is
    not only reputation management.

    Keyed on the address rather than the user: the same address can belong to
    different accounts over time, and it is the mailbox that bounced.
    """

    __tablename__ = "email_suppressions"

    email: Mapped[str] = mapped_column(
        LowercaseString(320), nullable=False, unique=True
    )
    # "bounced" or "complained". Kept as free text rather than an enum because it
    # records what a third party told us, and a provider adding a category should
    # not require a migration to write it down.
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    # The provider's own description, for a human deciding whether to lift it.
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_email_suppressions_created_at", "created_at"),)

    def __repr__(self) -> str:
        return f"<EmailSuppression {self.reason}>"
