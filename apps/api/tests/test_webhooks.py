"""Webhook tests.

Signing and the event catalogue are unit-tested. Registration, dispatch, and the
delivery state machine run against the real database and the real service code;
only the outbound HTTP call is faked, because a test must not make network calls, 
everything that decides an endpoint's fate is exercised for real.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.enums import WebhookDeliveryStatus
from app.db.session import get_db
from app.main import app
from app.modules.organizations.models import Organization
from app.modules.webhooks import destinations, service, signing
from app.modules.webhooks import events as event_catalog
from app.modules.webhooks.models import WebhookDelivery, WebhookEndpoint

pytestmark = pytest.mark.asyncio


# --- Unit: signing and events (no database) ---------------------------------


_SECRET_A = "whsec_a"  # noqa: S105 - test signing secret, not a real credential
_SECRET_B = "whsec_b"  # noqa: S105


class TestSigning:
    def test_sign_is_deterministic_and_verifiable(self) -> None:
        sig1 = signing.sign(secret=_SECRET_A, timestamp=1000, body='{"a":1}')
        sig2 = signing.sign(secret=_SECRET_A, timestamp=1000, body='{"a":1}')
        assert sig1 == sig2
        assert signing.sign(secret=_SECRET_B, timestamp=1000, body='{"a":1}') != sig1
        assert signing.sign(secret=_SECRET_A, timestamp=1001, body='{"a":1}') != sig1

    def test_header_shape(self) -> None:
        h = signing.signature_header(secret=_SECRET_A, timestamp=1000, body="{}")
        assert h.startswith("t=1000,v1=")


class TestEventCatalog:
    def test_unknown_events(self) -> None:
        assert event_catalog.unknown_events(["order.created", "nope"]) == ["nope"]
        assert event_catalog.unknown_events(["*"]) == []

    def test_wildcard_collapses(self) -> None:
        assert event_catalog.normalize_events(["order.created", "*"]) == ["*"]

    def test_matches(self) -> None:
        assert event_catalog.matches(["*"], "order.created")
        assert event_catalog.matches(["order.created"], "order.created")
        assert not event_catalog.matches(["order.created"], "order.completed")


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


async def sign_in(client: AsyncClient) -> tuple[str, uuid.UUID]:
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
    return body["tokens"]["access_token"], uuid.UUID(body["user"]["id"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeClient:
    """Stands in for httpx.AsyncClient: records calls, returns or raises."""

    def __init__(self, status_code: int | None = None, raise_exc: Exception | None = None):
        self.status_code = status_code
        self.raise_exc = raise_exc
        self.calls: list[tuple] = []

    async def post(self, url, content=None, headers=None):
        self.calls.append((url, content, headers))
        if self.raise_exc is not None:
            raise self.raise_exc
        return FakeResponse(self.status_code)


# --- Integration: management ------------------------------------------------


class TestManagement:
    async def test_create_returns_secret_once(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        resp = await client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.test/hook", "events": ["order.created"]},
            headers=auth(token),
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["secret"].startswith("whsec_")
        assert created["events"] == ["order.created"]

        listed = (await client.get("/api/v1/webhooks", headers=auth(token))).json()
        assert listed["total"] == 1
        assert "secret" not in listed["items"][0]

    async def test_http_url_is_rejected(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        resp = await client.post(
            "/api/v1/webhooks",
            json={"url": "http://example.test/hook", "events": ["*"]},
            headers=auth(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_unknown_event_rejected(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        resp = await client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.test/hook", "events": ["order.exploded"]},
            headers=auth(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_revoke(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        created = (
            await client.post(
                "/api/v1/webhooks",
                json={"url": "https://example.test/hook", "events": ["*"]},
                headers=auth(token),
            )
        ).json()
        deleted = await client.delete(
            f"/api/v1/webhooks/{created['id']}", headers=auth(token)
        )
        assert deleted.status_code == 204

    async def test_events_catalog_public(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/webhooks/events")
        assert resp.status_code == 200
        names = {e["event"] for e in resp.json()["events"]}
        assert "order.created" in names and "order.completed" in names


# --- Integration: dispatch and delivery -------------------------------------


async def _personal_org_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """The user's personal org, created for them at sign-in."""
    return (
        await db.execute(
            select(Organization.id).where(Organization.slug == f"u-{user_id.hex}")
        )
    ).scalar_one()


async def _make_endpoint(
    db: AsyncSession, user_id: uuid.UUID, events: list[str]
) -> WebhookEndpoint:
    ep = WebhookEndpoint(
        org_id=await _personal_org_id(db, user_id),
        created_by_user_id=user_id,
        url="https://example.test/hook",
        secret=_SECRET_A,
        events=events,
    )
    db.add(ep)
    await db.flush()
    return ep


async def _deliveries(db: AsyncSession, endpoint_id: uuid.UUID) -> list[WebhookDelivery]:
    rows = (
        await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id)
        )
    ).scalars()
    return list(rows)


class TestDispatch:
    async def test_dispatch_queues_only_matching_endpoints(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, user_id = await sign_in(client)
        subscribed = await _make_endpoint(db, user_id, ["order.created"])
        other = await _make_endpoint(db, user_id, ["order.completed"])

        queued = await service.dispatch(
            db,
            org_id=await _personal_org_id(db, user_id),
            event_type="order.created",
            data={"order": "x"},
        )
        assert queued == 1
        assert len(await _deliveries(db, subscribed.id)) == 1
        assert len(await _deliveries(db, other.id)) == 0

    async def test_revoked_endpoint_receives_nothing(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, user_id = await sign_in(client)
        ep = await _make_endpoint(db, user_id, ["*"])
        ep.revoked_at = datetime.now(UTC)
        await db.flush()
        queued = await service.dispatch(
            db,
            org_id=await _personal_org_id(db, user_id),
            event_type="order.created",
            data={},
        )
        assert queued == 0


@pytest.fixture(autouse=True)
def _endpoints_resolve_publicly(monkeypatch):
    """Make the fixture host resolve, without touching DNS.

    These tests use `example.test`, a reserved TLD that never resolves, which is
    correct: a test must not depend on somebody else's nameserver. Delivery
    refuses a destination it cannot resolve, so the guard would suppress every
    delivery here and the tests would assert nothing about delivery.

    The guard still runs in full; only the resolution it reads is stubbed, in
    the same spirit as the injected HTTP client. A test that wants the guard to
    refuse overrides this.
    """
    monkeypatch.setattr(destinations, "resolved_addresses", lambda host: ["93.184.216.34"])


class TestDelivery:
    async def _one_delivery(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> WebhookDelivery:
        ep = await _make_endpoint(db, user_id, ["*"])
        d = WebhookDelivery(
            endpoint_id=ep.id,
            event_type="order.created",
            payload={"n": 1},
            max_attempts=3,
        )
        db.add(d)
        await db.flush()
        return d

    async def test_suppressed_when_delivery_disabled(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", False)
        _, user_id = await sign_in(client)
        d = await self._one_delivery(db, user_id)
        fake = FakeClient(status_code=200)
        status = await service.deliver_one(db, fake, d)
        assert status == WebhookDeliveryStatus.SUPPRESSED
        assert fake.calls == []  # nothing was sent

    async def test_suppressed_when_the_destination_is_refused(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        """The guard is wired into delivery, not merely unit tested beside it.

        A name that resolved somewhere public at registration can resolve
        somewhere private by the time anything is sent, which is the whole
        reason the check runs again here. Nothing may leave the worker.
        """
        monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", True)
        monkeypatch.setattr(
            destinations, "resolved_addresses", lambda host: ["10.1.2.3"]
        )
        _, user_id = await sign_in(client)
        d = await self._one_delivery(db, user_id)
        fake = FakeClient(status_code=200)
        status = await service.deliver_one(db, fake, d)
        assert status == WebhookDeliveryStatus.SUPPRESSED
        assert fake.calls == [], "a request was made to a private address"
        assert "destination refused" in (d.last_error or "")

    async def test_success(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", True)
        _, user_id = await sign_in(client)
        d = await self._one_delivery(db, user_id)
        fake = FakeClient(status_code=200)
        status = await service.deliver_one(db, fake, d)
        assert status == WebhookDeliveryStatus.SUCCEEDED
        assert d.delivered_at is not None
        assert len(fake.calls) == 1
        # the signed request carried our headers
        _, _, headers = fake.calls[0]
        assert headers["X-Agoreum-Event"] == "order.created"
        assert headers["X-Agoreum-Signature"].startswith("t=")

    async def test_failure_then_retry_scheduled(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", True)
        _, user_id = await sign_in(client)
        d = await self._one_delivery(db, user_id)
        before = d.next_attempt_at
        status = await service.deliver_one(db, FakeClient(status_code=500), d)
        assert status == WebhookDeliveryStatus.FAILED
        assert d.attempts == 1
        assert d.next_attempt_at > before  # backoff pushed it out

    async def test_exhausts_after_max_attempts(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", True)
        _, user_id = await sign_in(client)
        d = await self._one_delivery(db, user_id)
        d.attempts = 2  # one attempt away from max_attempts=3
        await db.flush()
        status = await service.deliver_one(
            db, FakeClient(raise_exc=RuntimeError("connection refused")), d
        )
        assert status == WebhookDeliveryStatus.EXHAUSTED
        assert d.last_error is not None
