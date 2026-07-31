"""Webhook registration, event dispatch, and delivery.

Dispatch is called wherever the platform raises an event (via notifications), and
only writes outbox rows, it never makes an HTTP call on the request path. A
separate worker drains the outbox, signs each payload, POSTs it, and retries
failures with exponential backoff. Outbound HTTP is gated behind
`WEBHOOK_DELIVERY_ENABLED`: with it off, deliveries are recorded as suppressed
rather than sent, so the feature is exercisable without contacting anyone.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.enums import WebhookDeliveryStatus
from app.modules.users.models import User
from app.modules.webhooks import events as event_catalog
from app.modules.webhooks import signing
from app.modules.webhooks.models import WebhookDelivery, WebhookEndpoint

logger = get_logger(__name__)

MAX_ENDPOINTS_PER_USER = 20
# Backoff schedule: 30s, then doubling, capped at 6 hours. Slow enough to let a
# briefly-down receiver recover, bounded so a dead endpoint stops hammering.
_BACKOFF_BASE = timedelta(seconds=30)
_BACKOFF_CAP = timedelta(hours=6)


# --- Management -------------------------------------------------------------


async def create_endpoint(
    db: AsyncSession,
    *,
    user: User,
    url: str,
    events: list[str],
    description: str | None,
) -> tuple[WebhookEndpoint, str]:
    """Register an endpoint. Returns it and its signing secret (shown once)."""
    if not url.startswith("https://"):
        raise ValidationError(
            "A webhook URL must be https.", code="insecure_webhook_url"
        )
    unknown = event_catalog.unknown_events(events)
    if unknown:
        raise ValidationError(
            f"Unknown event(s): {', '.join(unknown)}.",
            code="unknown_event",
            details={"unknown": unknown},
        )
    subscribed = event_catalog.normalize_events(events)
    if not subscribed:
        raise ValidationError(
            "Subscribe to at least one event, or '*' for all.",
            code="no_events",
        )

    active = (
        await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.user_id == user.id,
                WebhookEndpoint.revoked_at.is_(None),
            )
        )
    ).scalars()
    if len(list(active)) >= MAX_ENDPOINTS_PER_USER:
        raise ConflictError(
            f"You already have the maximum of {MAX_ENDPOINTS_PER_USER} webhook "
            "endpoints. Remove one before adding another.",
            code="too_many_webhooks",
        )

    secret = signing.generate_secret()
    endpoint = WebhookEndpoint(
        user_id=user.id,
        url=url,
        description=description,
        secret=secret,
        events=subscribed,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint, secret


async def list_endpoints(db: AsyncSession, *, user: User) -> list[WebhookEndpoint]:
    rows = (
        await db.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.user_id == user.id)
            .order_by(WebhookEndpoint.created_at.desc())
        )
    ).scalars()
    return list(rows)


async def revoke_endpoint(
    db: AsyncSession, *, user: User, endpoint_id: uuid.UUID
) -> WebhookEndpoint:
    endpoint = (
        await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if endpoint is None:
        raise NotFoundError("No such webhook endpoint.")
    if endpoint.revoked_at is None:
        endpoint.revoked_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(endpoint)
    return endpoint


async def list_deliveries(
    db: AsyncSession, *, user: User, endpoint_id: uuid.UUID, limit: int
) -> list[WebhookDelivery]:
    # Confirm the endpoint belongs to the caller before exposing its deliveries.
    endpoint = (
        await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if endpoint is None:
        raise NotFoundError("No such webhook endpoint.")
    rows = (
        await db.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.endpoint_id == endpoint_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)


# --- Dispatch (enqueue only) ------------------------------------------------


async def dispatch(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_type: str,
    data: dict | None = None,
) -> int:
    """Queue this event for every active endpoint of the user subscribed to it.

    Writes outbox rows only, no HTTP here. Returns how many were queued. Never
    raises into the caller: a webhook problem must not fail the action that
    triggered the event.
    """
    try:
        endpoints = (
            await db.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.user_id == user_id,
                    WebhookEndpoint.revoked_at.is_(None),
                )
            )
        ).scalars()
        queued = 0
        for endpoint in endpoints:
            if not event_catalog.matches(endpoint.events, event_type):
                continue
            db.add(
                WebhookDelivery(
                    endpoint_id=endpoint.id,
                    event_type=event_type,
                    payload=data or {},
                    max_attempts=settings.WEBHOOK_MAX_ATTEMPTS,
                )
            )
            queued += 1
        if queued:
            await db.flush()
        return queued
    except Exception:  # pragma: no cover - defensive; never break the caller
        logger.exception("webhook_dispatch_failed", extra={"event_type": event_type})
        return 0


# --- Delivery (worker) ------------------------------------------------------


def _backoff(attempts: int) -> timedelta:
    delay = _BACKOFF_BASE * (2 ** max(0, attempts - 1))
    return min(delay, _BACKOFF_CAP)


def build_body(delivery: WebhookDelivery) -> str:
    """The exact JSON string that is signed and sent. Stable across retries."""
    envelope = {
        "id": str(delivery.event_id),
        "type": delivery.event_type,
        "created_at": delivery.created_at.astimezone(UTC).isoformat(),
        "data": delivery.payload,
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True)


async def claim_due(db: AsyncSession, *, limit: int) -> list[WebhookDelivery]:
    """Return deliveries that are due to be attempted, oldest first.

    The worker runs single-instance (like the indexer), so this does not lock rows;
    `deliver_one` commits each attempt as it goes. If the worker dies mid-batch, the
    unfinished rows keep their due time and are simply picked up next pass, 
    at-least-once delivery, which is why every delivery carries a stable id for the
    receiver to deduplicate on.
    """
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(
                    [WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.FAILED]
                ),
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
    ).scalars()
    return list(rows)


async def deliver_one(
    db: AsyncSession, client: httpx.AsyncClient, delivery: WebhookDelivery
) -> WebhookDeliveryStatus:
    """Attempt one delivery, update its record, and return the new status."""
    endpoint = (
        await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.endpoint_id)
        )
    ).scalar_one_or_none()

    delivery.attempts += 1
    now = datetime.now(UTC)

    if endpoint is None or endpoint.revoked_at is not None:
        # The endpoint was removed after this was queued. Stop, don't retry.
        delivery.status = WebhookDeliveryStatus.SUPPRESSED
        delivery.last_error = "endpoint no longer active"
        await db.commit()
        return delivery.status

    if not settings.WEBHOOK_DELIVERY_ENABLED:
        delivery.status = WebhookDeliveryStatus.SUPPRESSED
        delivery.last_error = "webhook delivery disabled in this environment"
        endpoint.last_delivery_at = now
        await db.commit()
        return delivery.status

    body = build_body(delivery)
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Agoreum-Webhooks/1",
        "X-Agoreum-Event": delivery.event_type,
        "X-Agoreum-Delivery": str(delivery.id),
        "X-Agoreum-Signature": signing.signature_header(
            secret=endpoint.secret, timestamp=timestamp, body=body
        ),
    }

    started = time.perf_counter()
    endpoint.last_delivery_at = now
    try:
        response = await client.post(endpoint.url, content=body, headers=headers)
        duration_ms = int((time.perf_counter() - started) * 1000)
        delivery.last_duration_ms = duration_ms
        delivery.last_status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryStatus.SUCCEEDED
            delivery.delivered_at = now
            delivery.last_error = None
            endpoint.last_success_at = now
            await db.commit()
            return delivery.status
        delivery.last_error = f"HTTP {response.status_code}"
    except Exception as exc:
        delivery.last_duration_ms = int((time.perf_counter() - started) * 1000)
        delivery.last_status_code = None
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:300]

    if delivery.attempts >= delivery.max_attempts:
        delivery.status = WebhookDeliveryStatus.EXHAUSTED
    else:
        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.next_attempt_at = now + _backoff(delivery.attempts)
    await db.commit()
    return delivery.status
