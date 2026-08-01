"""Read pageview counts from the self-hosted Umami database.

Creator analytics needs view counts, which live only in Umami. Rather than depend
on an Umami API token, this reads the Umami Postgres database directly (the same
self-hosted instance the site already sends events to) using the connection string
already configured for that service.

It is deliberately defensive: if analytics is not configured, or the Umami database
cannot be reached, it returns nothing. A view count is never fabricated; the caller
reports views as unavailable instead.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)


def _dsn() -> str:
    dsn = settings.UMAMI_DATABASE_URL.get_secret_value()
    # asyncpg wants a plain libpq URL, not a SQLAlchemy driver URL.
    for prefix, repl in (
        ("postgresql+asyncpg://", "postgresql://"),
        ("postgresql+psycopg://", "postgresql://"),
        ("postgres://", "postgresql://"),
    ):
        if dsn.startswith(prefix):
            dsn = repl + dsn[len(prefix) :]
            break
    return dsn


def path_patterns(agent_slugs: list[str]) -> list[str]:
    """SQL LIKE patterns matching a creator's public pages, across every locale.

    An agent's profile lives at `/{locale}/agents/{slug}` and its service pages at
    `/{locale}/agents/{slug}/services/...`, so both are matched by suffix.
    """
    patterns: list[str] = []
    for slug in agent_slugs:
        patterns.append(f"%/agents/{slug}")
        patterns.append(f"%/agents/{slug}/services/%")
    return patterns


async def total_pageviews(agent_slugs: list[str], since: datetime) -> int | None:
    """Total pageviews of the given agents' pages since `since`, or None if the
    Umami database is not configured or unreachable."""
    if not settings.analytics_views_enabled or not agent_slugs:
        return 0 if settings.analytics_views_enabled else None
    patterns = path_patterns(agent_slugs)
    try:
        conn = await asyncpg.connect(_dsn(), timeout=8)
        try:
            row = await conn.fetchval(
                """
                SELECT count(*) FROM website_event
                WHERE website_id = $1::uuid
                  AND event_type = 1
                  AND created_at >= $2
                  AND url_path LIKE ANY($3::text[])
                """,
                settings.UMAMI_WEBSITE_ID,
                since,
                patterns,
            )
            return int(row or 0)
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001 - any failure degrades to "unavailable"
        logger.warning("umami_pageviews_failed", exc_info=exc)
        return None


async def daily_pageviews(
    agent_slugs: list[str], since: datetime
) -> list[tuple[date, int]] | None:
    """Per-day pageview counts (UTC), or None if unavailable."""
    if not settings.analytics_views_enabled or not agent_slugs:
        return [] if settings.analytics_views_enabled else None
    patterns = path_patterns(agent_slugs)
    try:
        conn = await asyncpg.connect(_dsn(), timeout=8)
        try:
            rows = await conn.fetch(
                """
                SELECT date_trunc('day', created_at)::date AS day, count(*) AS views
                FROM website_event
                WHERE website_id = $1::uuid
                  AND event_type = 1
                  AND created_at >= $2
                  AND url_path LIKE ANY($3::text[])
                GROUP BY day
                ORDER BY day
                """,
                settings.UMAMI_WEBSITE_ID,
                since,
                patterns,
            )
            return [(r["day"], int(r["views"])) for r in rows]
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("umami_daily_pageviews_failed", exc_info=exc)
        return None
