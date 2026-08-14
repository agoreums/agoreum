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

from app.core import alerts
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

# Inbound mail. support@agoreum.xyz is published on five public pages and named
# in docs/security.md as the vulnerability disclosure channel, and mail arriving
# there used to announce itself to nobody: the first real report sat unread until
# it was found by accident. This is the announcement.
RECEIVED_EVENTS = frozenset({"email.received"})

# Addresses that only ever receive machine reports. Mail to these is recorded
# but does not page anybody.
#
# `dmarc@` exists solely as the `rua=` destination in the DMARC record. Every
# major receiver sends an aggregate report there daily, and Google alone had
# accounted for seven of the twelve messages this domain had ever received. Each
# one raised an operator alert saying mail had arrived, on the same channel that
# carries governance events, uptime failures and red builds.
#
# That is the failure the alert above was written to prevent, arriving from the
# other direction. A channel where most messages need no action stops being read,
# and the one report that matters is the one that gets skimmed past. The address
# is not published anywhere as a contact, so nothing human is expected here.
#
# Matched on the local part so it holds if the domain ever changes.
REPORT_ONLY_LOCAL_PARTS = frozenset({"dmarc"})


def _is_report_only(recipients: list) -> bool:
    """Whether every recipient is a machine-report address.

    Every recipient, not any: a message addressed to both a report address and a
    human one is still for a human. Anything unparseable counts as human, so an
    odd address errs toward paging rather than silence.
    """
    if not recipients:
        return False
    for address in recipients:
        local = str(address).split("@", 1)[0].strip().lower()
        if local not in REPORT_ONLY_LOCAL_PARTS:
            return False
    return True


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


async def _announce_received(data: dict, *, recipients: list) -> str:
    """Tell an operator that mail arrived. Never raises.

    Deliberately a summary and not the message. The body is written by anyone on
    the internet, it can be enormous, and it may contain exactly the sort of
    content a security report contains. The alert says who wrote, about what, and
    where to read it; reading it stays a deliberate act.

    A delivery failure is swallowed rather than reported upward, because the
    caller answers a provider that retries on anything except a 2xx, and retrying
    the whole webhook to fix a Telegram outage would replay it indefinitely.
    """
    if _is_report_only(recipients):
        # Recorded, not paged. The log line keeps it discoverable when somebody
        # goes looking, without spending an operator's attention on it.
        logger.info(
            "inbound_report_mail",
            extra={
                "to": alerts.sanitise(", ".join(str(r) for r in recipients), limit=120),
                "from": alerts.sanitise(str(data.get("from") or ""), limit=120),
            },
        )
        return "received: report address, not alerted"

    sender = alerts.sanitise(str(data.get("from") or ""), limit=120)
    subject = alerts.sanitise(str(data.get("subject") or ""), limit=200)
    to = alerts.sanitise(", ".join(str(r) for r in recipients), limit=120)
    received = alerts.sanitise(str(data.get("created_at") or ""), limit=40)

    sent = await alerts.notify_operator(
        "Mail received at an Agoreum address.\n\n"
        f"From: {sender}\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Received: {received}\n\n"
        "Read it in the Resend dashboard under Emails, Received. "
        "This address is the published security disclosure channel, so treat "
        "the contents as untrusted until you have judged them."
    )

    logger.info("inbound_mail_announced", extra={"alert_delivered": sent})
    return f"received: alerted={sent}"


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

    if event_type in RECEIVED_EVENTS:
        return await _announce_received(data, recipients=recipients)

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
