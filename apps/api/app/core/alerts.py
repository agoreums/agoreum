"""Operator alerts, over Telegram.

For things a person needs to look at rather than things a user is told about.
`notifications.notify` is the wrong tool for those: it targets a user, respects
their preferences, and goes out over email, which would make an alert depend on
the mail system that some alerts exist to report on.

Every function here fails quietly. An alert that cannot be delivered must never
break the thing that raised it, and the caller is usually a webhook that a
provider will otherwise retry forever.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 10.0

# Telegram's own cap is 4096 characters. Well under it, because an alert is a
# pointer to something, not a copy of it.
MAX_ALERT_CHARS = 1200


def alerting_available() -> tuple[bool, str]:
    """Whether an alert would actually go anywhere, and why not if it would not."""
    if not settings.TELEGRAM_BOT_TOKEN.get_secret_value():
        return False, "no Telegram bot token is configured"
    if not settings.TELEGRAM_CHAT_ID:
        return False, "no Telegram chat id is configured"
    return True, ""


def sanitise(value: str | None, *, limit: int = 200) -> str:
    """Make a piece of third-party text safe to put in an alert.

    Everything interesting in these alerts was written by whoever sent the email,
    so it is hostile input. Three specific problems:

    Control characters and newlines let a sender forge extra lines and fake
    fields that were never in the message.

    A leading @ is a Telegram mention, so an unfiltered subject could ping a
    group. The character is kept, since removing it silently would misreport what
    was sent, but a zero-width joiner is inserted so it does not resolve.

    Length. A subject can be enormous, and one long field must not push the rest
    of the alert out.
    """
    if not value:
        return "(none)"
    cleaned = "".join(" " if ch in "\r\n\t" else ch for ch in value if ch.isprintable() or ch in " ")
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.replace("@", "@‍")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned or "(empty)"


async def notify_operator(text: str) -> bool:
    """Send an alert. Returns whether it was delivered.

    No parse_mode is set, so Telegram renders the message literally. That is the
    point: with Markdown or HTML enabled, text quoted from an email could close a
    tag or open a link, and the alert would render as something other than what
    arrived.
    """
    available, reason = alerting_available()
    if not available:
        logger.warning("operator_alert_not_sent", extra={"reason": reason})
        return False

    body = text[:MAX_ALERT_CHARS]
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": body,
                    "disable_web_page_preview": True,
                },
            )
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning(
            "operator_alert_failed", extra={"error": f"{type(exc).__name__}: {exc}"}
        )
        return False

    if response.status_code >= 400:
        # The response body carries Telegram's description of what was wrong, but
        # it also echoes the request, so only the status is logged.
        logger.warning(
            "operator_alert_rejected", extra={"status": response.status_code}
        )
        return False

    logger.info("operator_alert_sent")
    return True
