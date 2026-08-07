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
        user.email = "unproven@example.com"
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
        user.email = "unproven2@example.com"
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
        user.email = "proven@example.com"
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
        user.email = "verified@example.com"
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
            "/api/v1/auth/me", json={"email": "x@example.com"}, headers=headers
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
