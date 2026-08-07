"""Receiving bounce and complaint events from Resend.

Resend signs webhooks with Svix, which is an HMAC over "{id}.{timestamp}.{body}"
using a base64 secret prefixed `whsec_`. Verifying that signature is the whole
security of this endpoint: it is unauthenticated by necessity, since a provider
cannot hold a session, so the signature is the only thing distinguishing a real
bounce report from anyone on the internet claiming an address bounced.

That matters more than it first appears. An attacker who could forge these could
suppress any address at will, which silently stops that person receiving security
notices. Suppression is a denial-of-service primitive if it is not authenticated.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.notifications import service as notifications

logger = get_logger(__name__)

# Svix rejects anything older than five minutes, and so do we. Without a
# freshness check a captured payload could be replayed indefinitely.
TOLERANCE_SECONDS = 5 * 60

# Only these change state. Delivery and open events are ignored: they are not
# actionable, and recording them would be tracking rather than deliverability.
BOUNCE_EVENTS = frozenset({"email.bounced"})
COMPLAINT_EVENTS = frozenset({"email.complained"})


class WebhookRejected(Exception):
    """The request did not come from Resend, or is too old to trust."""


def _secret() -> bytes | None:
    """The signing secret, decoded. None when unconfigured."""
    raw = settings.RESEND_WEBHOOK_SECRET.get_secret_value()
    if not raw:
        return None
    # Svix secrets are base64 after the whsec_ prefix.
    return base64.b64decode(raw.removeprefix("whsec_"))


def verify(
    *,
    body: bytes,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
) -> None:
    """Raise unless this request genuinely came from Resend, recently.

    Every failure raises the same exception type with a deliberately unspecific
    message. Telling a caller *which* check failed helps them iterate towards a
    forgery.
    """
    secret = _secret()
    if secret is None:
        raise WebhookRejected("webhook signing is not configured")
    if not (svix_id and svix_timestamp and svix_signature):
        raise WebhookRejected("missing signature headers")

    try:
        sent_at = int(svix_timestamp)
    except ValueError as exc:
        raise WebhookRejected("bad signature headers") from exc

    if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
        raise WebhookRejected("bad signature headers")

    signed = f"{svix_id}.{svix_timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest())

    # The header carries one or more space-separated "v1,<sig>" pairs, so a
    # secret can be rotated without dropping in-flight deliveries. Any match is
    # enough, and every comparison is constant time.
    for part in svix_signature.split():
        _, _, candidate = part.partition(",")
        if candidate and hmac.compare_digest(candidate.encode(), expected):
            return

    raise WebhookRejected("bad signature headers")


async def handle(db: AsyncSession, *, payload: dict) -> str:
    """Apply a verified webhook. Returns what was done, for logging.

    Unknown event types are accepted and ignored rather than rejected. Returning
    an error for an event we simply do not act on would make a provider retry it
    forever and could get the endpoint disabled at their end.
    """
    event_type = str(payload.get("type") or "")
    data = payload.get("data") or {}

    recipients = data.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]

    if event_type in BOUNCE_EVENTS:
        reason = "bounce"
    elif event_type in COMPLAINT_EVENTS:
        reason = "complaint"
    else:
        return f"ignored {event_type or 'untyped event'}"

    detail = None
    bounce = data.get("bounce") or {}
    if isinstance(bounce, dict):
        # Soft bounces are transient (a full mailbox, a greylist). Suppressing on
        # one would cut somebody off for a problem that fixes itself.
        if reason == "bounce" and str(bounce.get("type", "")).lower() == "soft":
            return "ignored soft bounce"
        detail = str(bounce.get("message") or bounce.get("subType") or "")[:512] or None

    suppressed = 0
    for address in recipients:
        if not isinstance(address, str) or "@" not in address:
            continue
        await notifications.suppress_email(
            db, email=address, reason=reason, detail=detail
        )
        suppressed += 1

    logger.info(
        "resend_webhook_applied",
        extra={"event_type": event_type, "suppressed": suppressed},
    )
    return f"{reason}: suppressed {suppressed}"
