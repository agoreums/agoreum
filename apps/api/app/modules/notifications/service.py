"""Notification creation and delivery.

A notification is created once and delivered over one or more channels. Delivery
per channel is tracked separately, because an in-app notification can succeed
while its email fails, and reporting a single "sent" would hide that.

**Email sending is gated.** Real messages go to real inboxes, which is not
something to do as a side effect of a test run or a local experiment. Sending is
only attempted when `EMAIL_SENDING_ENABLED` is true *and* an API key is present.
Otherwise the delivery is recorded as suppressed with the reason, so the
intention is visible without anyone being contacted.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.enums import (
    NotificationCategory,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from app.modules.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from app.modules.users.models import User

logger = get_logger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
EMAIL_TIMEOUT_SECONDS = 15.0

# Security notices are never suppressible. A user must always learn that someone
# signed in as them or changed where their money is sent, whatever their
# preferences say.
NON_SUPPRESSIBLE = frozenset({NotificationCategory.SECURITY})


@dataclass(frozen=True)
class DeliveryOutcome:
    channel: NotificationChannel
    status: NotificationDeliveryStatus
    detail: str | None = None


def email_sending_available() -> tuple[bool, str | None]:
    """Whether a real email could actually be sent right now, and why not.

    Returned as a reason rather than a bare boolean so the block is explainable
    in logs, in the admin view, and to a developer wondering why nothing arrived.
    """
    if not settings.EMAIL_SENDING_ENABLED:
        return False, "email sending is disabled in this environment"
    if not settings.RESEND_API_KEY.get_secret_value():
        return False, "no Resend API key is configured"
    return True, None


# --- Creation ---------------------------------------------------------------


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    category: NotificationCategory,
    event_type: str,
    title: str,
    body: str | None = None,
    action_url: str | None = None,
    payload: dict | None = None,
    related_order_id: uuid.UUID | None = None,
    related_agent_id: uuid.UUID | None = None,
    channels: tuple[NotificationChannel, ...] = (
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
    ),
    allow_unverified_email: bool = False,
) -> Notification:
    """Create a notification and attempt delivery over the requested channels.

    `allow_unverified_email` exists for exactly one caller, the verification
    message, which has to reach an unproven address in order to prove it. It
    defaults to False so that every other notification is silently held back
    rather than mailed to an address nobody confirmed. Adding a second caller
    should require an argument as to why.
    """
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("No such user.")

    notification = Notification(
        user_id=user_id,
        category=category,
        event_type=event_type,
        title=title,
        body=body,
        action_url=action_url,
        locale=user.preferred_locale,
        payload=payload,
        related_order_id=related_order_id,
        related_agent_id=related_agent_id,
    )
    db.add(notification)
    await db.flush()

    for channel in channels:
        await _deliver(
            db,
            notification=notification,
            user=user,
            channel=channel,
            allow_unverified_email=allow_unverified_email,
        )

    await db.flush()

    # The same event that raises an in-app notification is offered to the
    # recipient's organization webhook endpoints. This only queues outbox rows; a
    # worker sends them. It never raises, so a webhook problem cannot fail the
    # action behind the event.
    from app.modules.organizations import service as org_service
    from app.modules.webhooks import service as webhooks

    org = await org_service.ensure_personal_org(db, user=user)
    await webhooks.dispatch(
        db, org_id=org.id, event_type=event_type, data=payload
    )

    logger.info(
        "notification_created",
        extra={
            "user_id": str(user_id),
            "event_type": event_type,
            "category": category.value,
        },
    )
    return notification


async def _deliver(
    db: AsyncSession,
    *,
    notification: Notification,
    user: User,
    channel: NotificationChannel,
    allow_unverified_email: bool = False,
) -> NotificationDelivery:
    delivery = NotificationDelivery(
        notification_id=notification.id,
        channel=channel,
        status=NotificationDeliveryStatus.PENDING,
    )

    allowed = await _channel_enabled(
        db, user_id=user.id, category=notification.category, channel=channel
    )
    if not allowed:
        delivery.status = NotificationDeliveryStatus.SUPPRESSED
        delivery.last_error = "the recipient has disabled this channel"
        db.add(delivery)
        await db.flush()
        return delivery

    if channel == NotificationChannel.IN_APP:
        # In-app delivery is the row existing; there is nothing to transmit.
        delivery.status = NotificationDeliveryStatus.DELIVERED
        delivery.sent_at = datetime.now(UTC)
        delivery.delivered_at = delivery.sent_at
        db.add(delivery)
        await db.flush()
        return delivery

    if channel == NotificationChannel.EMAIL:
        delivery.destination = user.email
        if not user.email:
            delivery.status = NotificationDeliveryStatus.SUPPRESSED
            delivery.last_error = "the recipient has no email address"
            db.add(delivery)
            await db.flush()
            return delivery

        # An address nobody has proven is just a string somebody typed. Sending to
        # it makes the platform a way to mail a stranger, carrying this domain's
        # reputation while doing it, and the person receiving it never asked for
        # anything. The single exception is the verification message itself, which
        # by definition has to reach an unproven address to prove it.
        if user.email_verified_at is None and not allow_unverified_email:
            delivery.status = NotificationDeliveryStatus.SUPPRESSED
            delivery.last_error = "the recipient's email address is not verified"
            db.add(delivery)
            await db.flush()
            return delivery

        db.add(delivery)
        await db.flush()
        await _send_email(db, delivery=delivery, notification=notification)
        return delivery

    db.add(delivery)
    await db.flush()
    return delivery


async def _channel_enabled(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    category: NotificationCategory,
    channel: NotificationChannel,
) -> bool:
    """Whether the recipient wants this category on this channel.

    Absence of a preference means the platform default (enabled). Security
    notices ignore preferences entirely.
    """
    if category in NON_SUPPRESSIBLE:
        return True

    preference = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.category == category,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()

    return True if preference is None else preference.enabled


# --- Email ------------------------------------------------------------------


async def _send_email(
    db: AsyncSession,
    *,
    delivery: NotificationDelivery,
    notification: Notification,
) -> None:
    """Send through Resend, or record precisely why it was not sent."""
    available, reason = email_sending_available()
    if not available:
        delivery.status = NotificationDeliveryStatus.SUPPRESSED
        delivery.last_error = reason
        await db.flush()
        logger.info(
            "email_suppressed",
            extra={"reason": reason, "event_type": notification.event_type},
        )
        return

    delivery.attempt_count += 1

    try:
        async with httpx.AsyncClient(timeout=EMAIL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": (
                        f"Bearer {settings.RESEND_API_KEY.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"Agoreum <{settings.EMAIL_FROM}>",
                    "to": [delivery.destination],
                    "subject": notification.title,
                    "text": _plain_text(notification),
                },
            )
    except httpx.HTTPError as exc:
        delivery.status = NotificationDeliveryStatus.FAILED
        delivery.failed_at = datetime.now(UTC)
        delivery.last_error = f"transport error: {type(exc).__name__}"
        await db.flush()
        logger.warning(
            "email_send_failed", extra={"error_type": type(exc).__name__}
        )
        return

    if response.status_code >= 400:
        delivery.status = NotificationDeliveryStatus.FAILED
        delivery.failed_at = datetime.now(UTC)
        # The body can contain the recipient address; only the status is kept.
        delivery.last_error = f"provider returned HTTP {response.status_code}"
        await db.flush()
        logger.warning(
            "email_send_rejected", extra={"status_code": response.status_code}
        )
        return

    body = response.json() if response.content else {}
    delivery.status = NotificationDeliveryStatus.SENT
    delivery.sent_at = datetime.now(UTC)
    delivery.provider_message_id = body.get("id")
    await db.flush()

    logger.info(
        "email_sent",
        extra={
            "event_type": notification.event_type,
            "provider_message_id": delivery.provider_message_id,
        },
    )


def _plain_text(notification: Notification) -> str:
    lines = [notification.title, ""]
    if notification.body:
        lines += [notification.body, ""]
    if notification.action_url:
        lines += [notification.action_url, ""]
    # A blank line already separates the body from this signature block.
    lines += [
        "Agoreum",
        settings.APP_URL,
    ]
    return "\n".join(lines)


# --- Reads and state --------------------------------------------------------


async def list_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    unread_only: bool = False,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    """Return a page of notifications, the total, and the unread count."""
    conditions = [Notification.user_id == user_id, Notification.archived_at.is_(None)]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))

    total = (
        await db.execute(
            select(func.count()).select_from(Notification).where(*conditions)
        )
    ).scalar_one()

    unread = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.archived_at.is_(None),
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return list(rows), total, unread


async def mark_read(
    db: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if notification is None:
        raise NotFoundError("No such notification.")

    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
    return notification


async def mark_all_read(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.flush()
    return result.rowcount or 0


async def set_preference(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    category: NotificationCategory,
    channel: NotificationChannel,
    enabled: bool,
) -> NotificationPreference:
    """Record a delivery preference.

    Security notices cannot be switched off; the attempt is refused rather than
    silently ignored, so a user is never misled about what they will receive.
    """
    if category in NON_SUPPRESSIBLE and not enabled:
        from app.core.errors import ConflictError

        raise ConflictError(
            "Security notifications cannot be turned off.",
            code="category_not_suppressible",
        )

    preference = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.category == category,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()

    if preference is None:
        preference = NotificationPreference(
            user_id=user_id, category=category, channel=channel, enabled=enabled
        )
        db.add(preference)
    else:
        preference.enabled = enabled

    await db.flush()
    return preference


async def list_preferences(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[NotificationPreference]:
    rows = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
    ).scalars().all()
    return list(rows)
