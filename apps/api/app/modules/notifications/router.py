"""Notification endpoints."""
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.modules.notifications import resend_webhook, service
from app.modules.notifications.schemas import (
    EmailStatus,
    NotificationList,
    NotificationPublic,
    PreferencePublic,
    PreferenceUpdate,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList, summary="Your notifications")
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> NotificationList:
    items, total, unread = await service.list_for_user(
        db, user_id=user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationList(
        items=[NotificationPublic.model_validate(n) for n in items],
        total=total,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationPublic,
    summary="Mark one as read",
)
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> NotificationPublic:
    notification = await service.mark_read(
        db, user_id=user.id, notification_id=notification_id
    )
    return NotificationPublic.model_validate(notification)


@router.post(
    "/read-all",
    status_code=status.HTTP_200_OK,
    summary="Mark everything as read",
)
async def mark_all_read(user: CurrentUser, db: DbSession) -> dict[str, int]:
    return {"marked": await service.mark_all_read(db, user_id=user.id)}


@router.get(
    "/preferences",
    response_model=list[PreferencePublic],
    summary="Your delivery preferences",
)
async def preferences(user: CurrentUser, db: DbSession) -> list[PreferencePublic]:
    """Only explicitly-set preferences are returned; anything absent uses the
    platform default, which is enabled."""
    rows = await service.list_preferences(db, user_id=user.id)
    return [PreferencePublic.model_validate(p) for p in rows]


@router.put(
    "/preferences",
    response_model=PreferencePublic,
    summary="Set a delivery preference",
)
async def set_preference(
    payload: PreferenceUpdate, user: CurrentUser, db: DbSession
) -> PreferencePublic:
    """Security notices cannot be disabled; that attempt is refused rather than
    silently ignored."""
    preference = await service.set_preference(
        db,
        user_id=user.id,
        category=payload.category,
        channel=payload.channel,
        enabled=payload.enabled,
    )
    return PreferencePublic.model_validate(preference)


@router.get(
    "/email-status",
    response_model=EmailStatus,
    summary="Whether email would actually be sent from this deployment",
)
async def email_status() -> EmailStatus:
    enabled, reason = service.email_sending_available()
    return EmailStatus(
        enabled=enabled, reason=reason, from_address=settings.EMAIL_FROM
    )


@router.post(
    "/webhooks/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bounce and complaint events from Resend",
    include_in_schema=False,
    dependencies=[Depends(limiter("notifications:resend_webhook"))],
)
async def resend_events(
    request: Request,
    db: DbSession,
    svix_id: Annotated[str | None, Header(alias="svix-id")] = None,
    svix_timestamp: Annotated[str | None, Header(alias="svix-timestamp")] = None,
    svix_signature: Annotated[str | None, Header(alias="svix-signature")] = None,
) -> None:
    """Suppress addresses that hard bounced or generated a spam complaint.

    Unauthenticated by necessity, since a provider cannot hold a session. The
    Svix signature over the raw body is therefore the only thing separating a
    real bounce report from anyone on the internet claiming an address bounced,
    and an attacker who could forge one could suppress any address and silently
    stop that person receiving security notices.

    The raw bytes are read before parsing, because the signature covers exactly
    what was sent. Re-serialising parsed JSON would change the bytes and the
    check would never pass.

    Every rejection is a flat 401 with no detail. Telling a caller which check
    failed helps them iterate towards a forgery.
    """
    body = await request.body()

    try:
        resend_webhook.verify(
            body=body,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
        )
    except resend_webhook.WebhookRejected:
        raise HTTPException(status_code=401, detail="unauthorised") from None

    try:
        payload = json.loads(body)
    except ValueError:
        # Verified as genuinely from Resend but unparseable. Accepting it stops
        # an infinite retry loop over something a retry cannot fix.
        return

    if isinstance(payload, dict):
        await resend_webhook.handle(db, payload=payload)
