"""API key tests.

Exercised through the real HTTP stack and a real database: a signed-in user mints
keys, then those keys authenticate the programmatic API exactly as an SDK would.
Nothing about the auth path is stubbed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.modules.apikeys.models import ApiKey
from app.modules.apikeys.scopes import normalize_scopes, unknown_scopes

pytestmark = pytest.mark.asyncio


class Wallet:
    def __init__(self) -> None:
        self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address.lower()

    def sign(self, message: str) -> str:
        return self._account.sign_message(encode_defunct(text=message)).signature.hex()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        # Fail fast when nothing is listening. The default waits out a full
        # TCP timeout per test, which turns a skipped suite on a machine with
        # no database into an hour of nothing.
        connect_args={"timeout": 5},
    )
    try:
        async with eng.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        await eng.dispose()
        pytest.skip(f"no database reachable: {type(exc).__name__}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


async def sign_in(client: AsyncClient) -> str:
    wallet = Wallet()
    challenge = (
        await client.post(
            "/api/v1/auth/nonce",
            json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
        )
    ).json()
    body = (
        await client.post(
            "/api/v1/auth/signin",
            json={
                "message": challenge["message"],
                "signature": wallet.sign(challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
    ).json()
    return body["tokens"]["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestApiKeyManagement:
    async def test_create_returns_token_once_and_hides_it_after(
        self, client: AsyncClient
    ) -> None:
        token = await sign_in(client)
        resp = await client.post(
            "/api/v1/api-keys",
            json={"name": "CI pipeline", "scopes": ["marketplace:read", "orders:read"]},
            headers=auth(token),
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["token"].startswith("ak_")
        assert created["prefix"] == created["token"][:12]
        assert created["scopes"] == ["marketplace:read", "orders:read"]

        # Listing never exposes the secret again.
        listed = (await client.get("/api/v1/api-keys", headers=auth(token))).json()
        assert listed["total"] == 1
        assert "token" not in listed["items"][0]
        assert listed["items"][0]["prefix"] == created["prefix"]

    async def test_default_scope_is_least_privilege(self, client: AsyncClient) -> None:
        token = await sign_in(client)
        created = (
            await client.post(
                "/api/v1/api-keys", json={"name": "no scopes"}, headers=auth(token)
            )
        ).json()
        assert created["scopes"] == ["marketplace:read"]

    async def test_unknown_scope_is_rejected(self, client: AsyncClient) -> None:
        token = await sign_in(client)
        resp = await client.post(
            "/api/v1/api-keys",
            json={"name": "bad", "scopes": ["orders:delete"]},
            headers=auth(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_scopes_catalog_is_public(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/api-keys/scopes")
        assert resp.status_code == 200
        scopes = {s["scope"] for s in resp.json()["scopes"]}
        assert "marketplace:read" in scopes
        assert "orders:write" in scopes


class TestApiKeyAuthentication:
    async def _mint(self, client: AsyncClient, token: str, scopes: list[str]) -> str:
        return (
            await client.post(
                "/api/v1/api-keys",
                json={"name": "k", "scopes": scopes},
                headers=auth(token),
            )
        ).json()["token"]

    async def test_key_authenticates_via_x_api_key_header(
        self, client: AsyncClient
    ) -> None:
        session = await sign_in(client)
        key = await self._mint(client, session, ["marketplace:read", "orders:read"])
        resp = await client.get("/api/v1/me", headers={"X-API-Key": key})
        assert resp.status_code == 200, resp.text
        me = resp.json()
        assert me["auth"]["method"] == "api_key"
        assert me["auth"]["scopes"] == ["marketplace:read", "orders:read"]
        assert me["auth"]["api_key_prefix"] == key[:12]

    async def test_key_authenticates_via_bearer(self, client: AsyncClient) -> None:
        session = await sign_in(client)
        key = await self._mint(client, session, ["marketplace:read"])
        resp = await client.get("/api/v1/me", headers=auth(key))
        assert resp.status_code == 200, resp.text
        assert resp.json()["auth"]["method"] == "api_key"

    async def test_session_principal_holds_all_scopes(
        self, client: AsyncClient
    ) -> None:
        session = await sign_in(client)
        me = (await client.get("/api/v1/me", headers=auth(session))).json()
        assert me["auth"]["method"] == "session"
        assert "orders:write" in me["auth"]["scopes"]

    async def test_revoked_key_is_rejected(self, client: AsyncClient) -> None:
        session = await sign_in(client)
        created = (
            await client.post(
                "/api/v1/api-keys", json={"name": "k"}, headers=auth(session)
            )
        ).json()
        deleted = await client.delete(
            f"/api/v1/api-keys/{created['id']}", headers=auth(session)
        )
        assert deleted.status_code == 204
        resp = await client.get("/api/v1/me", headers={"X-API-Key": created["token"]})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "key_revoked"

    async def test_garbage_key_is_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/me", headers={"X-API-Key": "not-a-key"})
        assert resp.status_code == 401

    async def test_unauthenticated_me_is_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/me")
        assert resp.status_code == 401


class TestScopedApiAccess:
    """API keys reaching real, scope-gated endpoints, the point of the whole thing."""

    async def _mint(self, client: AsyncClient, session: str, scopes: list[str]) -> str:
        return (
            await client.post(
                "/api/v1/api-keys",
                json={"name": "k", "scopes": scopes},
                headers=auth(session),
            )
        ).json()["token"]

    async def test_orders_read_scope_grants_access(self, client: AsyncClient) -> None:
        session = await sign_in(client)
        key = await self._mint(client, session, ["orders:read"])
        resp = await client.get("/api/v1/orders", headers={"X-API-Key": key})
        assert resp.status_code == 200, resp.text
        assert resp.json() == []  # a new account has no orders, but access is granted

    async def test_missing_scope_is_forbidden(self, client: AsyncClient) -> None:
        session = await sign_in(client)
        key = await self._mint(client, session, ["marketplace:read"])
        resp = await client.get("/api/v1/orders", headers={"X-API-Key": key})
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["error"]["code"] == "insufficient_scope"
        assert "orders:read" in body["error"]["details"]["missing"]

    async def test_agents_read_scope_grants_access(self, client: AsyncClient) -> None:
        session = await sign_in(client)
        key = await self._mint(client, session, ["agents:read"])
        resp = await client.get("/api/v1/agents/mine", headers={"X-API-Key": key})
        assert resp.status_code == 200, resp.text

    async def test_session_reaches_scoped_endpoint_without_a_key(
        self, client: AsyncClient
    ) -> None:
        # The web app keeps working: a session holds every scope.
        session = await sign_in(client)
        resp = await client.get("/api/v1/orders", headers=auth(session))
        assert resp.status_code == 200, resp.text


class TestScopeLogic:
    """Unit coverage for the scope helpers and principal, no database needed."""

    def test_normalize_dedupes_and_orders(self) -> None:
        assert normalize_scopes(["orders:read", "marketplace:read", "orders:read"]) == [
            "marketplace:read",
            "orders:read",
        ]

    def test_normalize_empty_is_default(self) -> None:
        assert normalize_scopes([]) == ["marketplace:read"]
        assert normalize_scopes(None) == ["marketplace:read"]

    def test_unknown_scopes_detected(self) -> None:
        assert unknown_scopes(["marketplace:read", "nope:read"]) == ["nope:read"]

    def test_principal_scope_check(self) -> None:
        p = Principal(user=None, scopes=frozenset({"orders:read"}), api_key=None)
        assert p.has_scopes(frozenset({"orders:read"}))
        assert not p.has_scopes(frozenset({"orders:write"}))

    def test_key_is_active_respects_expiry_and_revocation(self) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        assert ApiKey(expires_at=None, revoked_at=None).is_active
        assert not ApiKey(expires_at=past, revoked_at=None).is_active
        assert not ApiKey(expires_at=None, revoked_at=past).is_active
