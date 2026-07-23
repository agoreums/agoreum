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
