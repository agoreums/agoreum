"""Shared test fixtures.

Tests drive the app through httpx's in-process ASGI transport rather than
Starlette's threaded TestClient. This exercises the real async stack end to end
without spawning a blocking portal thread, which keeps the suite deterministic
and avoids an interpreter-level crash observed on Python 3.14 during teardown.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.main import app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the application, with lifespan events run."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac


@pytest.fixture(autouse=True)
def _no_live_operator_alerts(monkeypatch):
    """No test may page a real Telegram chat or Discord channel.

    This machine's .env carries working alert credentials, so any test reaching
    notify_operator posts to a channel a person actually reads. That happened:
    a test asserting the unconfigured path left two messages saying "test" in the
    private security channel, because it blanked Telegram and the Discord
    fallback then succeeded.

    Blanked for the whole suite rather than per test, for the same reason
    EMAIL_SENDING_ENABLED is false everywhere: a guard that has to be remembered
    is a guard that gets forgotten. A test wanting to exercise delivery patches
    the transport, not the credentials.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", SecretStr(""))
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr(""))
    monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "")
