"""Which events notify whom, and what the email channel refuses to do.

The valuable assertions here are the negative ones. An unverified address must
never receive anything except the message that proves it, and nothing may leave
this deployment at all while sending is disabled.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.enums import (
    NotificationCategory,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from app.modules.auth import service as auth_service
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationDelivery
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


class Wallet:
    def __init__(self) -> None:
        self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address.lower()

    def sign(self, message: str) -> str:
        return self._account.sign_message(encode_defunct(text=message)).signature.hex()


@pytest.fixture
def wallet() -> Wallet:
    return Wallet()


def an_email(label: str = "user") -> str:
    """A fresh address, unique to this call.

    Same reason as in test_email_verification.py: these were literals against a
    unique constraint, so the rows survived the run and the second run of the
    same suite failed on `profile_conflict`. Duplicated rather than imported
    because `tests/` is not a package and these files cannot import each other,
    which is the existing convention here for `Wallet` too.
    """
    return f"{label}-{uuid.uuid4().hex[:12]}@example.com"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        # Generous on purpose. The earlier value was 5 seconds, to "fail fast
        # when nothing is listening", but that is not what makes it fast:
        # a closed port on loopback refuses the connection in about two
        # seconds whatever the timeout, measured both ways. The timeout only
        # bites when a database *is* listening and slow, which on a loaded
        # machine turned into an error in one full run and a silently skipped
        # test in the next. A skipped test is the failure this project treats
        # as serious, so the setting that caused it is the one that was wrong.
        connect_args={"timeout": 30},
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


async def _sign_in(client: AsyncClient, wallet: Wallet) -> dict:
    resp = await client.post(
        "/api/v1/auth/nonce",
        json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    resp = await client.post(
        "/api/v1/auth/signin",
        json={
            "message": body["message"],
            "signature": wallet.sign(body["message"]),
            "nonce": body["nonce"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _deliveries(
    db: AsyncSession, user_id: uuid.UUID, channel: NotificationChannel
) -> list[NotificationDelivery]:
    from app.modules.notifications.models import Notification

    rows = await db.execute(
        sa.select(NotificationDelivery)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            Notification.user_id == user_id,
            NotificationDelivery.channel == channel,
        )
    )
    return list(rows.scalars().all())


def _enable_sending(monkeypatch) -> None:
    """Make `email_sending_available()` true for one test.

    Both halves are needed: the flag and a key. Patching only the flag makes the
    row suppress for a missing key instead of queueing, which is what CI caught.

    The key is a fake, so a call that escaped a test would be rejected by the
    provider rather than delivered. Tests that could reach the network replace
    the HTTP client outright as well.
    """
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "EMAIL_SENDING_ENABLED", True)
    monkeypatch.setattr(
        settings, "RESEND_API_KEY", SecretStr("re_not_a_real_key_for_tests")
    )


class TestUnverifiedAddressesAreRefused:
    async def test_email_is_suppressed_for_an_unverified_address(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The property the whole verification step exists to enforce.

        An address nobody proved must not receive ordinary notifications, or the
        platform becomes a way to mail a stranger.
        """
        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = None
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert len(email) == 1
        assert email[0].status == NotificationDeliveryStatus.SUPPRESSED
        assert "not verified" in (email[0].last_error or "")

        # The in-app copy still lands: suppressing email must not silently drop
        # the notification altogether.
        in_app = await _deliveries(db, user.id, NotificationChannel.IN_APP)
        assert len(in_app) == 1
        assert in_app[0].status == NotificationDeliveryStatus.DELIVERED

    async def test_the_verification_message_is_the_documented_exception(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """It has to reach an unproven address; that is its entire purpose."""
        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = None
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.SECURITY,
            event_type="account.email_verification",
            title="Confirm your email address",
            channels=(NotificationChannel.EMAIL,),
            allow_unverified_email=True,
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert len(email) == 1
        # Not suppressed for being unverified. It is still not sent, because
        # sending is disabled, which the next test covers.
        assert "not verified" not in (email[0].last_error or "")

    async def test_a_verified_address_is_not_suppressed(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        from datetime import UTC, datetime

        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert len(email) == 1
        assert "not verified" not in (email[0].last_error or "")


class TestNothingLeavesThisDeployment:
    async def test_sending_is_disabled_in_the_test_environment(self) -> None:
        """The guard the whole suite depends on.

        If this ever passes with sending enabled, every other test in this file
        is one Resend call away from mailing a real address.
        """
        available, reason = notifications.email_sending_available()
        assert available is False
        assert reason

    async def test_no_delivery_is_ever_marked_sent(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        from datetime import UTC, datetime

        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.PAYMENT,
            event_type="order.released",
            title="Test",
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert email
        for row in email:
            assert row.status != NotificationDeliveryStatus.SENT
            assert row.sent_at is None


class TestAnAddresslessAccount:
    """The regression that took sign-in down.

    Almost every account has no email address, and a notification for one has
    nowhere to send the email copy. Writing that delivery row violated a check
    constraint, the error escaped the notification code into the sign-in handler,
    and every returning sign-in answered 503.
    """

    async def test_signing_in_twice_still_works_without_an_email(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The second sign-in is the one that notifies, so it is the one that broke.

        `db` is unused here, but taking it means this skips alongside the rest
        when no database is reachable rather than failing on the app's own
        connection. A test that goes red for environmental reasons is noise, and
        noise is how a real failure gets waved through.
        """
        first = await _sign_in(client, wallet)
        assert first["user"]["email"] is None

        second = await client.post(
            "/api/v1/auth/nonce",
            json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
        )
        assert second.status_code == 201
        body = second.json()
        resp = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": body["message"],
                "signature": wallet.sign(body["message"]),
                "nonce": body["nonce"],
            },
            headers={"User-Agent": "a-different-client/1.0"},
        )
        assert resp.status_code == 200, resp.text

    async def test_the_email_copy_is_recorded_as_suppressed(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The row is kept rather than skipped, because it is the record of why
        nothing was sent."""
        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        assert user.email is None

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert len(email) == 1
        assert email[0].status == NotificationDeliveryStatus.SUPPRESSED
        assert email[0].destination is None
        assert "no email address" in (email[0].last_error or "")


class TestAFailureCannotPoisonTheCallersTransaction:
    async def test_the_caller_can_still_write_after_a_failed_notification(
        self, db: AsyncSession
    ) -> None:
        """Swallowing the exception is not enough on its own.

        Once a flush fails, every later statement on that session raises
        PendingRollbackError, so the indexer's own work dies anyway and the
        handler that caught the error only hides the reason. The savepoint is
        what makes the promise true.
        """
        from app.modules.notifications import events

        await events._safe_notify(
            db,
            user_id=uuid.uuid4(),
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        # The session must still be usable. Without the savepoint this raises.
        assert (await db.execute(sa.select(sa.literal(1)))).scalar_one() == 1


class TestSignInNotice:
    async def test_a_first_ever_signin_is_not_announced(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """A security notice that fires when nothing is wrong gets ignored."""
        body = await _sign_in(client, wallet)
        user_id = uuid.UUID(body["user"]["id"])

        from app.modules.notifications.models import Notification

        rows = await db.execute(
            sa.select(Notification).where(
                Notification.user_id == user_id,
                Notification.event_type == "account.new_signin",
            )
        )
        assert rows.scalars().all() == []

    async def test_the_verification_endpoint_reports_what_actually_happened(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """sent=false while delivery is off, rather than a comforting lie."""
        body = await _sign_in(client, wallet)
        access = body["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        await client.patch(
            "/api/v1/auth/me", json={"email": an_email()}, headers=headers
        )
        resp = await client.post("/api/v1/auth/me/email/verify", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["sent"] is False
        assert "disabled" in resp.json()["detail"] or "key" in resp.json()["detail"]


class TestFailuresDoNotPropagate:
    async def test_a_notification_failure_never_raises_into_the_caller(
        self, db: AsyncSession
    ) -> None:
        """The indexer must keep projecting chain state whatever happens here.

        An order that silently stays unfunded is a buyer whose money is committed
        and whose work never starts, which is far worse than a missed email.
        """
        from app.modules.notifications import events

        # A user id that does not exist makes notify raise NotFoundError.
        await events._safe_notify(
            db,
            user_id=uuid.uuid4(),
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

    async def test_auth_service_exposes_the_verification_helpers(self) -> None:
        assert hasattr(auth_service, "issue_email_verification")
        assert hasattr(auth_service, "confirm_email_verification")


class TestTheSignInNoticeCannotBeVentriloquised:
    """The user agent is chosen by whoever signed in.

    In the one message that exists to tell somebody another person accessed their
    account, that other person controls a span of text the reader trusts.
    """

    def test_forged_lines_cannot_be_injected(self) -> None:
        from app.modules.notifications import events

        forged = "Chrome\n\nThis alert is informational, no action required."
        out = events._describe(forged, limit=100)
        assert "\n" not in out

    def test_control_characters_are_removed(self) -> None:
        from app.modules.notifications import events

        raw = "Chrome\x00\x07\x1b[31m"
        assert "\x00" not in events._describe(raw, limit=100)
        assert "\x1b" not in events._describe(raw, limit=100)

    def test_a_long_value_cannot_crowd_out_the_advice(self) -> None:
        from app.modules.notifications import events

        assert len(events._describe("x" * 5000, limit=100)) <= 100

    def test_a_missing_value_reads_as_missing(self) -> None:
        from app.modules.notifications import events

        assert events._describe(None, limit=100) == "(not reported)"
        assert events._describe("   ", limit=100) == "(not reported)"

    async def test_the_notice_disclaims_the_device_string(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The framing is the mitigation: quoted, labelled, and marked unverified."""
        from app.modules.notifications import events

        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))

        await events.new_session_signin(
            db,
            user=user,
            ip_address="203.0.113.9",
            user_agent="Chrome. Verified device, no action required.",
        )

        from app.modules.notifications.models import Notification

        row = (
            await db.execute(
                sa.select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.event_type == "account.new_signin",
                )
            )
        ).scalars().first()
        assert row is not None
        assert "described itself as:" in row.body
        assert "is not verified" in row.body


class TestSendingIsOffTheRequestPath:
    """No request may wait on Resend.

    Funding an order used to block on the notification's HTTP call, so a slow
    provider slowed the thing that caused it.
    """

    async def test_notify_makes_no_outbound_call(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet, monkeypatch
    ) -> None:
        from datetime import UTC, datetime

        called: list[str] = []

        class Forbidden:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k):
                called.append("post")
                raise AssertionError("notify must not call the provider inline")

        monkeypatch.setattr(notifications.httpx, "AsyncClient", Forbidden)
        _enable_sending(monkeypatch)

        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        assert called == []
        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert len(email) == 1
        assert email[0].status == NotificationDeliveryStatus.PENDING
        assert email[0].next_retry_at is not None, "it must be claimable by the worker"
        assert email[0].sent_at is None

    async def test_a_queued_row_is_claimable(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet, monkeypatch
    ) -> None:
        from datetime import UTC, datetime

        _enable_sending(monkeypatch)
        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        claimable = an_email("claimable")
        user.email = claimable
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.PAYMENT,
            event_type="order.released",
            title="Test",
        )
        await db.flush()

        due = await notifications.claim_due_emails(db, limit=50)
        assert any(d.destination == claimable for d in due)

    async def test_nothing_is_queued_while_sending_is_disabled(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """Otherwise the queue grows without bound behind a flag that is off."""
        from datetime import UTC, datetime

        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        user.email = an_email()
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )

        email = await _deliveries(db, user.id, NotificationChannel.EMAIL)
        assert email[0].status == NotificationDeliveryStatus.SUPPRESSED
        assert email[0].next_retry_at is None

    async def test_an_address_suppressed_after_queueing_is_not_mailed(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet, monkeypatch
    ) -> None:
        """The window between queueing and sending is exactly when a bounce lands."""
        from datetime import UTC, datetime

        _enable_sending(monkeypatch)
        body = await _sign_in(client, wallet)
        user = await db.get(User, uuid.UUID(body["user"]["id"]))
        bounced = an_email("bounced")
        user.email = bounced
        user.email_verified_at = datetime.now(UTC)
        await db.flush()

        await notifications.notify(
            db,
            user_id=user.id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title="Test",
        )
        await db.flush()

        # The bounce arrives after the row was queued.
        await notifications.suppress_email(
            db, email=bounced, reason="bounce"
        )

        # If the re-check regressed, this turns a silent send into a failure.
        class Forbidden:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k):
                raise AssertionError("a suppressed address must not be mailed")

        monkeypatch.setattr(notifications.httpx, "AsyncClient", Forbidden)

        row = (await _deliveries(db, user.id, NotificationChannel.EMAIL))[0]
        status = await notifications.send_one(db, delivery=row)
        assert status == NotificationDeliveryStatus.SUPPRESSED
        assert row.sent_at is None

    def test_a_permanent_rejection_is_not_retried_forever(self) -> None:
        from app.modules.notifications.models import NotificationDelivery

        row = NotificationDelivery(
            notification_id=uuid.uuid4(),
            channel=NotificationChannel.EMAIL,
            status=NotificationDeliveryStatus.FAILED,
        )
        row.attempt_count = notifications.MAX_EMAIL_ATTEMPTS
        notifications._schedule_retry(row)
        assert row.next_retry_at is None, "a spent row must drop out of the queue"

    def test_backoff_widens_between_attempts(self) -> None:
        from app.modules.notifications.models import NotificationDelivery

        previous = None
        for attempt in range(1, 5):
            row = NotificationDelivery(
                notification_id=uuid.uuid4(),
                channel=NotificationChannel.EMAIL,
                status=NotificationDeliveryStatus.FAILED,
            )
            row.attempt_count = attempt
            notifications._schedule_retry(row)
            assert row.next_retry_at is not None
            if previous is not None:
                assert row.next_retry_at >= previous
            previous = row.next_retry_at
