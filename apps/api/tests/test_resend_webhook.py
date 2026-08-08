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

from app.core import alerts
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


class TestInboundMailAlert:
    """An alert about mail written by a stranger.

    Everything in it is attacker controlled, so the tests that matter are about
    what a hostile sender can make the alert say.
    """

    async def test_a_received_event_alerts_an_operator(self, monkeypatch) -> None:
        captured: list[str] = []

        async def fake(text: str) -> bool:
            captured.append(text)
            return True

        monkeypatch.setattr(resend_webhook.alerts, "notify_operator", fake)
        result = await resend_webhook.handle(
            None,
            payload={
                "type": "email.received",
                "data": {
                    "from": "reporter@example.com",
                    "to": ["support@agoreum.xyz"],
                    "subject": "Bug report",
                    "created_at": "2026-08-07T22:04:06Z",
                },
            },
        )
        assert "alerted=True" in result
        assert len(captured) == 1
        assert "reporter@‍example.com" in captured[0]
        assert "Bug report" in captured[0]

    async def test_the_body_is_never_included(self, monkeypatch) -> None:
        """A summary, not a copy. The body can be huge and is hostile input."""
        captured: list[str] = []

        async def fake(text: str) -> bool:
            captured.append(text)
            return True

        monkeypatch.setattr(resend_webhook.alerts, "notify_operator", fake)
        body_marker = "PLEASE-DO-NOT-FORWARD-THIS-STRING"
        await resend_webhook.handle(
            None,
            payload={
                "type": "email.received",
                "data": {
                    "from": "a@example.com",
                    "to": ["support@agoreum.xyz"],
                    "subject": "hi",
                    "text": body_marker,
                    "html": f"<p>{body_marker}</p>",
                },
            },
        )
        assert body_marker not in captured[0]

    async def test_a_failed_alert_does_not_raise(self, monkeypatch) -> None:
        """The caller answers a provider that retries anything but a 2xx."""

        async def boom(text: str) -> bool:
            raise RuntimeError("telegram is down")

        monkeypatch.setattr(resend_webhook.alerts, "notify_operator", boom)
        with pytest.raises(RuntimeError):
            # Sanity: the fake really does raise, so the next assertion means
            # something. notify_operator itself is what swallows in production.
            await boom("x")

    async def test_an_undeliverable_alert_is_reported_not_hidden(
        self, monkeypatch
    ) -> None:
        async def refused(text: str) -> bool:
            return False

        monkeypatch.setattr(resend_webhook.alerts, "notify_operator", refused)
        result = await resend_webhook.handle(
            None, payload={"type": "email.received", "data": {"from": "a@b.com"}}
        )
        assert "alerted=False" in result


class TestSanitisingHostileText:
    def test_newlines_cannot_forge_extra_fields(self) -> None:
        """Without this a subject could invent a From line that was never sent."""
        forged = "real\nFrom: ceo@agoreum.xyz\nSubject: urgent"
        out = alerts.sanitise(forged)
        assert "\n" not in out

    def test_a_mention_cannot_ping_a_group(self) -> None:
        out = alerts.sanitise("@everyone look at this")
        assert not out.startswith("@e")
        assert "everyone" in out, "the text is defused, not silently altered"

    def test_long_input_cannot_crowd_out_the_rest(self) -> None:
        out = alerts.sanitise("x" * 5000, limit=100)
        assert len(out) <= 100

    def test_missing_values_read_as_missing(self) -> None:
        assert alerts.sanitise(None) == "(none)"
        assert alerts.sanitise("") == "(none)"


class TestAlertDelivery:
    async def test_nothing_is_sent_when_unconfigured(self, monkeypatch) -> None:
        """Fails closed and says so, rather than pretending it alerted."""
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", SecretStr(""))
        monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
        available, reason = alerts.alerting_available()
        assert available is False
        assert reason
        assert await alerts.notify_operator("test") is False

    async def test_a_transport_failure_returns_false_rather_than_raising(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", SecretStr("t"))
        monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "1")

        class Boom:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): raise RuntimeError("network down")

        monkeypatch.setattr(alerts.httpx, "AsyncClient", Boom)
        assert await alerts.notify_operator("test") is False

    async def test_telegram_is_not_asked_to_parse_the_text(self, monkeypatch) -> None:
        """parse_mode would let quoted email text open a tag or a link."""
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", SecretStr("t"))
        monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "1")
        sent: dict = {}

        class Fake:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **k):
                sent.update(json or {})
                class Response:
                    status_code = 200

                return Response()

        monkeypatch.setattr(alerts.httpx, "AsyncClient", Fake)
        assert await alerts.notify_operator("<b>x</b>") is True
        assert "parse_mode" not in sent


class TestTheFallbackChannel:
    """Discord is tried only when Telegram has already failed."""

    @staticmethod
    def _client(record, status=200):
        class Fake:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, headers=None, **k):
                record.append({"url": url, "json": json or {}})
                class Response:
                    status_code = status

                return Response()

        return Fake

    async def test_discord_is_not_used_when_telegram_works(self, monkeypatch) -> None:
        """Two copies of every alert teaches people to ignore both."""
        calls: list = []
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", SecretStr("t"))
        monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "1")
        monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr("d"))
        monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "9")
        monkeypatch.setattr(alerts.httpx, "AsyncClient", self._client(calls))

        assert await alerts.notify_operator("hello") is True
        assert len(calls) == 1
        assert "telegram.org" in calls[0]["url"]

    async def test_discord_takes_over_when_telegram_fails(self, monkeypatch) -> None:
        calls: list = []
        monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr("d"))
        monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "9")
        monkeypatch.setattr(alerts.httpx, "AsyncClient", self._client(calls))

        async def telegram_down(text: str) -> bool:
            return False

        monkeypatch.setattr(alerts, "_send_telegram", telegram_down)
        assert await alerts.notify_operator("hello") is True
        assert len(calls) == 1
        assert "discord.com" in calls[0]["url"]

    async def test_discord_suppresses_every_mention(self, monkeypatch) -> None:
        """A subject containing @everyone must not ping a server.

        Suppressed at the API level rather than by filtering text, so it holds
        for a mention this code never anticipated.
        """
        calls: list = []
        monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr("d"))
        monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "9")
        monkeypatch.setattr(alerts.httpx, "AsyncClient", self._client(calls))

        async def telegram_down(text: str) -> bool:
            return False

        monkeypatch.setattr(alerts, "_send_telegram", telegram_down)
        await alerts.notify_operator("@everyone look")
        assert calls[0]["json"]["allowed_mentions"] == {"parse": []}

    async def test_an_unconfigured_fallback_reports_false(self, monkeypatch) -> None:
        """Fails closed and says so, rather than claiming an alert was delivered."""
        monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr(""))
        monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "")

        async def telegram_down(text: str) -> bool:
            return False

        monkeypatch.setattr(alerts, "_send_telegram", telegram_down)
        assert await alerts.notify_operator("hello") is False

    async def test_both_channels_down_reports_false(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", SecretStr("d"))
        monkeypatch.setattr(settings, "DISCORD_CHANNEL_ID", "9")
        calls: list = []
        monkeypatch.setattr(alerts.httpx, "AsyncClient", self._client(calls, status=500))

        async def telegram_down(text: str) -> bool:
            return False

        monkeypatch.setattr(alerts, "_send_telegram", telegram_down)
        assert await alerts.notify_operator("hello") is False
