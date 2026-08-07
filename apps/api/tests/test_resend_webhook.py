"""Bounce and complaint handling, and the signature that guards it.

The endpoint is unauthenticated by necessity, so the Svix signature is the entire
security boundary. Suppression is a denial-of-service primitive if forgeable: an
attacker who could post fake bounces could stop any address receiving security
notices, silently and permanently.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.modules.notifications import resend_webhook

pytestmark = pytest.mark.asyncio


# `tests/` is not a package, so each file carries its own database fixtures
# rather than importing across files. Skipping as a unit when no database is
# reachable keeps the signature tests, which need none, from being lost with it.
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
    """A session inside a transaction that is always rolled back."""
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


SECRET_RAW = base64.b64encode(b"a-test-signing-secret-32-bytes!!").decode()
SECRET = f"whsec_{SECRET_RAW}"


def _sign(body: bytes, msg_id: str = "msg_1", ts: int | None = None) -> dict[str, str]:
    """Sign a body the way Svix does, returning real HTTP headers."""
    ts = ts if ts is not None else int(time.time())
    signed = f"{msg_id}.{ts}.".encode() + body
    mac = hmac.new(base64.b64decode(SECRET_RAW), signed, hashlib.sha256).digest()
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v1,{base64.b64encode(mac).decode()}",
    }


def _as_args(headers: dict[str, str]) -> dict[str, str]:
    """The same headers as keyword arguments for `verify`."""
    return {key.replace("-", "_"): value for key, value in headers.items()}


@pytest.fixture(autouse=True)
def _configured_secret(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", SecretStr(SECRET))


class TestSignature:
    async def test_a_correctly_signed_request_is_accepted(self) -> None:
        body = json.dumps({"type": "email.delivered"}).encode()
        resend_webhook.verify(body=body, **_as_args(_sign(body)))

    async def test_a_forged_signature_is_rejected(self) -> None:
        body = json.dumps({"type": "email.bounced"}).encode()
        headers = _sign(body)
        headers["svix-signature"] = "v1," + base64.b64encode(b"nope" * 8).decode()
        with pytest.raises(resend_webhook.WebhookRejected):
            resend_webhook.verify(body=body, **_as_args(headers))

    async def test_a_modified_body_is_rejected(self) -> None:
        """The signature covers the bytes, so tampering must invalidate it."""
        body = json.dumps({"type": "email.bounced", "data": {"to": ["a@x.com"]}}).encode()
        headers = _sign(body)
        tampered = json.dumps({"type": "email.bounced", "data": {"to": ["victim@x.com"]}}).encode()
        with pytest.raises(resend_webhook.WebhookRejected):
            resend_webhook.verify(body=tampered, **_as_args(headers))

    async def test_an_old_signature_is_rejected(self) -> None:
        """Without a freshness check a captured payload replays forever."""
        body = b"{}"
        old = int(time.time()) - (resend_webhook.TOLERANCE_SECONDS + 60)
        with pytest.raises(resend_webhook.WebhookRejected):
            resend_webhook.verify(body=body, **_as_args(_sign(body, ts=old)))

    async def test_missing_headers_are_rejected(self) -> None:
        with pytest.raises(resend_webhook.WebhookRejected):
            resend_webhook.verify(
                body=b"{}", svix_id=None, svix_timestamp=None, svix_signature=None
            )

    async def test_an_unconfigured_secret_rejects_everything(self, monkeypatch) -> None:
        """Absent configuration must fail closed, not open."""
        monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", SecretStr(""))
        body = b"{}"
        with pytest.raises(resend_webhook.WebhookRejected):
            resend_webhook.verify(body=body, **_as_args(_sign(body)))

    async def test_rotation_is_supported_by_multiple_signatures(self) -> None:
        """Several space-separated signatures let a secret rotate without loss."""
        body = b'{"type":"email.delivered"}'
        headers = _sign(body)
        good = headers["svix-signature"]
        headers["svix-signature"] = "v1," + base64.b64encode(b"old" * 11).decode() + " " + good
        resend_webhook.verify(body=body, **_as_args(headers))


class TestEndpoint:
    async def test_an_unsigned_post_is_refused(self, client) -> None:
        resp = await client.post(
            "/api/v1/notifications/webhooks/resend",
            json={"type": "email.bounced", "data": {"to": ["victim@example.com"]}},
        )
        assert resp.status_code == 401

    async def test_the_rejection_reveals_nothing(self, client) -> None:
        """A caller must not learn which check failed and iterate towards a forgery."""
        resp = await client.post(
            "/api/v1/notifications/webhooks/resend",
            json={"type": "email.bounced"},
            headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,zz"},
        )
        assert resp.status_code == 401
        assert "signature" not in resp.text.lower()
        assert "timestamp" not in resp.text.lower()


class TestEventHandling:
    async def test_a_soft_bounce_does_not_suppress(self, db) -> None:
        """A full mailbox fixes itself; cutting somebody off for it is wrong."""
        result = await resend_webhook.handle(
            db,
            payload={
                "type": "email.bounced",
                "data": {"to": ["soft@example.com"], "bounce": {"type": "Soft"}},
            },
        )
        assert "ignored" in result
        assert (
            await resend_webhook.notifications.suppression_for(db, email="soft@example.com") is None
        )

    async def test_a_hard_bounce_suppresses(self, db) -> None:
        await resend_webhook.handle(
            db,
            payload={
                "type": "email.bounced",
                "data": {
                    "to": ["hard@example.com"],
                    "bounce": {"type": "Permanent", "message": "no such user"},
                },
            },
        )
        row = await resend_webhook.notifications.suppression_for(db, email="hard@example.com")
        assert row is not None
        assert row.reason == "bounce"

    async def test_a_complaint_suppresses(self, db) -> None:
        await resend_webhook.handle(
            db,
            payload={"type": "email.complained", "data": {"to": ["spam@example.com"]}},
        )
        row = await resend_webhook.notifications.suppression_for(db, email="spam@example.com")
        assert row is not None
        assert row.reason == "complaint"

    async def test_repeated_events_are_idempotent(self, db) -> None:
        """Providers redeliver. The first reason is the one that explains it."""
        payload = {
            "type": "email.bounced",
            "data": {"to": ["dupe@example.com"], "bounce": {"type": "Permanent"}},
        }
        await resend_webhook.handle(db, payload=payload)
        await resend_webhook.handle(db, payload=payload)

        import sqlalchemy as sa

        from app.modules.notifications.models import EmailSuppression

        rows = (
            (
                await db.execute(
                    sa.select(EmailSuppression).where(EmailSuppression.email == "dupe@example.com")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_an_unknown_event_is_ignored_not_rejected(self, db) -> None:
        """Erroring would make the provider retry forever and disable the endpoint."""
        result = await resend_webhook.handle(
            db, payload={"type": "email.opened", "data": {"to": ["a@example.com"]}}
        )
        assert "ignored" in result
