"""GitHub verification tests.

The login normaliser and the gist check are unit-tested; the challenge lifecycle
runs against the real database and HTTP stack. Only the outbound call to GitHub is
faked — a test must not reach the network — but everything that decides whether an
account is verified runs for real.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.errors import ValidationError
from app.db.session import get_db
from app.main import app
from app.modules.agents import github_check, service

pytestmark = pytest.mark.asyncio


# --- Unit: login normalisation ----------------------------------------------


class TestNormalizeLogin:
    def test_accepts_plain_handle(self) -> None:
        assert service._normalize_github_login("Agoreums") == "agoreums"

    def test_strips_at_and_url(self) -> None:
        assert service._normalize_github_login("@Agoreums") == "agoreums"
        assert (
            service._normalize_github_login("https://github.com/Agoreums/repo")
            == "agoreums"
        )

    def test_rejects_invalid(self) -> None:
        for bad in ["", "-nope", "has space", "a" * 40, "under_score"]:
            with pytest.raises(ValidationError):
                service._normalize_github_login(bad)


# --- Unit: gist check (fake GitHub) -----------------------------------------


class _FakeResp:
    def __init__(self, status_code: int, data: object) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> object:
        return self._data


class _FakeClient:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get(self, url: str, headers: dict | None = None) -> _FakeResp:
        return self._resp


def _patch_github(monkeypatch, resp: _FakeResp) -> None:
    monkeypatch.setattr(
        github_check.httpx, "AsyncClient", lambda **kw: _FakeClient(resp)
    )


class TestGistCheck:
    async def test_token_in_description(self, monkeypatch) -> None:
        _patch_github(monkeypatch, _FakeResp(200, [{"description": "tok_123", "files": {}}]))
        found, err = await github_check.check_gist("someone", "tok_123")
        assert found and err is None

    async def test_token_in_filename(self, monkeypatch) -> None:
        _patch_github(
            monkeypatch, _FakeResp(200, [{"description": "", "files": {"tok_123.txt": {}}}])
        )
        found, _ = await github_check.check_gist("someone", "tok_123")
        assert found

    async def test_token_absent(self, monkeypatch) -> None:
        _patch_github(monkeypatch, _FakeResp(200, [{"description": "hi", "files": {}}]))
        found, err = await github_check.check_gist("someone", "tok_123")
        assert not found and err

    async def test_unknown_account(self, monkeypatch) -> None:
        _patch_github(monkeypatch, _FakeResp(404, {}))
        found, err = await github_check.check_gist("nobody", "tok_123")
        assert not found and "not found" in err.lower()

    async def test_rate_limited(self, monkeypatch) -> None:
        _patch_github(monkeypatch, _FakeResp(403, {}))
        found, err = await github_check.check_gist("someone", "tok_123")
        assert not found and "rate limit" in err.lower()


# --- Integration fixtures ---------------------------------------------------


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
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
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


async def make_agent(client: AsyncClient, token: str) -> str:
    slug = f"agent-{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/api/v1/agents",
        json={"slug": slug, "name": "Atlas", "tagline": "Research"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return slug


class TestGithubChallengeFlow:
    async def test_create_challenge_returns_token_and_instructions(
        self, client: AsyncClient
    ) -> None:
        token = await sign_in(client)
        slug = await make_agent(client, token)
        resp = await client.post(
            f"/api/v1/agents/{slug}/github-challenges",
            json={"github_login": "@Agoreums"},
            headers=auth(token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["github_login"] == "agoreums"
        assert body["token"].startswith("agoreum-verification=")
        assert "gist" in body["instructions"].lower()

    async def test_invalid_login_rejected(self, client: AsyncClient) -> None:
        token = await sign_in(client)
        slug = await make_agent(client, token)
        resp = await client.post(
            f"/api/v1/agents/{slug}/github-challenges",
            json={"github_login": "not a login"},
            headers=auth(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_verify_success_marks_agent(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        token = await sign_in(client)
        slug = await make_agent(client, token)
        created = (
            await client.post(
                f"/api/v1/agents/{slug}/github-challenges",
                json={"github_login": "agoreums"},
                headers=auth(token),
            )
        ).json()

        # The proof is observed for real in production; here the observation is faked.
        async def _found(login, tok):
            return True, None

        monkeypatch.setattr(github_check, "check_gist", _found)

        verified = await client.post(
            f"/api/v1/agents/{slug}/github-challenges/{created['id']}/verify",
            headers=auth(token),
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["verified_at"] is not None

        agent = (
            await client.get(f"/api/v1/agents/{slug}", headers=auth(token))
        ).json()
        assert agent["verified_github"] == "agoreums"

    async def test_verify_failure_does_not_mark(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        token = await sign_in(client)
        slug = await make_agent(client, token)
        created = (
            await client.post(
                f"/api/v1/agents/{slug}/github-challenges",
                json={"github_login": "agoreums"},
                headers=auth(token),
            )
        ).json()

        async def _not_found(login, tok):
            return False, "The verification token was not found."

        monkeypatch.setattr(github_check, "check_gist", _not_found)

        resp = await client.post(
            f"/api/v1/agents/{slug}/github-challenges/{created['id']}/verify",
            headers=auth(token),
        )
        assert resp.status_code == 409
        agent = (
            await client.get(f"/api/v1/agents/{slug}", headers=auth(token))
        ).json()
        assert agent["verified_github"] is None
