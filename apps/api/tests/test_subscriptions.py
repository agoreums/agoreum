"""Subscription tests.

The event decoder is unit-tested. The indexer apply path, the only thing that may
activate a subscription, runs against the real database with synthesised but
correctly-encoded on-chain events, so the never-fabricate rule is exercised
directly: no event, no subscription.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.chain import subscriptions as contract
from app.chain.subscription_indexer import apply_event
from app.core.config import settings
from app.db.enums import UserRole
from app.db.session import get_db
from app.main import app
from app.modules.subscriptions.models import Subscription, SubscriptionPayment
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

MONTH = 30 * 24 * 3600


def _topic_addr(addr: str) -> str:
    return "0x" + bytes(12).hex() + addr.lower().removeprefix("0x")


def _topic_uint(n: int) -> str:
    return "0x" + n.to_bytes(32, "big").hex()


def make_subscribed_log(
    *,
    subscriber: str,
    plan_id: int,
    token: str,
    amount_units: int,
    period_start: int,
    period_end: int,
    tx_hash: str,
    log_index: int = 0,
    block_number: int = 100,
    block_hash: str | None = None,
) -> dict:
    data = abi_encode(
        ["uint256", "uint64", "uint64"], [amount_units, period_start, period_end]
    )
    return {
        "topics": [
            contract.event_topic("Subscribed"),
            _topic_addr(subscriber),
            _topic_uint(plan_id),
            _topic_addr(token),
        ],
        "data": "0x" + data.hex(),
        "blockNumber": block_number,
        "blockHash": block_hash or ("0x" + b"\x11".hex() * 32),
        "transactionHash": tx_hash,
        "logIndex": log_index,
    }


class TestDecode:
    def test_decodes_subscribed(self) -> None:
        sub = "0x" + "ab" * 20
        tok = "0x" + "cd" * 20
        log = make_subscribed_log(
            subscriber=sub, plan_id=7, token=tok, amount_units=10_000_000,
            period_start=1000, period_end=1000 + MONTH, tx_hash="0x" + "ee" * 32,
        )
        event = contract.decode_log(log)
        assert event is not None
        assert event.name == "Subscribed"
        assert event.args["subscriber"] == sub
        assert event.args["planId"] == 7
        assert event.args["amountPaid"] == 10_000_000
        assert event.args["periodEnd"] == 1000 + MONTH


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
    except Exception as exc:  # pragma: no cover
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


async def sign_in(client: AsyncClient) -> tuple[str, str]:
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
    return body["tokens"]["access_token"], wallet.address


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_admin(db: AsyncSession, address: str) -> None:
    user = (
        await db.execute(select(User).where(User.primary_address == address.lower()))
    ).scalar_one()
    user.role = UserRole.ADMIN
    await db.flush()


PLAN = {
    "plan_id": 1,
    "name": "Pro Monthly",
    "tier": "pro",
    "interval": "monthly",
    "token_address": "0x" + "cd" * 20,
    "price": "10.00",
    "period_seconds": MONTH,
}


class TestPlansAndInstructions:
    async def test_admin_creates_plan_public_lists_it(self, client: AsyncClient, db) -> None:
        token, address = await sign_in(client)
        await make_admin(db, address)

        created = await client.post("/api/v1/subscriptions/plans", json=PLAN, headers=auth(token))
        assert created.status_code == 201, created.text

        plans = (await client.get("/api/v1/subscriptions/plans")).json()
        assert any(p["plan_id"] == 1 and p["tier"] == "pro" for p in plans)

    async def test_non_admin_cannot_create_plan(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        resp = await client.post("/api/v1/subscriptions/plans", json=PLAN, headers=auth(token))
        assert resp.status_code == 403

    async def test_instructions_when_configured(
        self, client: AsyncClient, db, monkeypatch
    ) -> None:
        token, address = await sign_in(client)
        await make_admin(db, address)
        await client.post("/api/v1/subscriptions/plans", json=PLAN, headers=auth(token))

        monkeypatch.setattr(settings, "SUBSCRIPTIONS_CONTRACT_ADDRESS", "0x" + "ef" * 20)
        resp = await client.get("/api/v1/subscriptions/plans/1/instructions")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["price_base_units"] == "10000000"  # 10 USDC at 6 decimals
        assert body["subscription_contract"] == "0x" + "ef" * 20

    async def test_instructions_unconfigured_is_503(
        self, client: AsyncClient, db, monkeypatch
    ) -> None:
        token, address = await sign_in(client)
        await make_admin(db, address)
        await client.post("/api/v1/subscriptions/plans", json=PLAN, headers=auth(token))
        monkeypatch.setattr(settings, "SUBSCRIPTIONS_CONTRACT_ADDRESS", None)
        resp = await client.get("/api/v1/subscriptions/plans/1/instructions")
        assert resp.status_code == 503


class TestIndexerApply:
    async def test_subscribed_event_activates_and_links_user(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token, address = await sign_in(client)  # creates a user + verified wallet
        now = int(datetime.now(UTC).timestamp())

        event = contract.decode_log(
            make_subscribed_log(
                subscriber=address, plan_id=1, token="0x" + "cd" * 20,
                amount_units=10_000_000, period_start=now, period_end=now + MONTH,
                tx_hash="0x" + "a1" * 32,
            )
        )
        outcome = await apply_event(db, event)
        assert outcome == "applied"

        sub = (
            await db.execute(
                select(Subscription).where(Subscription.subscriber_address == address.lower())
            )
        ).scalar_one()
        assert sub.is_active
        assert sub.user_id is not None  # linked to the signed-in user's wallet
        assert sub.status == "active"

        # It shows up on the user's own endpoint.
        me = (await client.get("/api/v1/subscriptions/me", headers=auth(token))).json()
        assert me[0]["plan_id"] == 1 and me[0]["status"] == "active"

        # Idempotent: re-applying the same log does nothing new.
        assert await apply_event(db, event) == "duplicate"

    async def test_renew_stacks_and_records_each_payment(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, address = await sign_in(client)
        now = int(datetime.now(UTC).timestamp())
        for i in range(2):
            end = now + MONTH * (i + 1)
            event = contract.decode_log(
                make_subscribed_log(
                    subscriber=address, plan_id=1, token="0x" + "cd" * 20,
                    amount_units=10_000_000, period_start=now, period_end=end,
                    tx_hash="0x" + f"{i:02x}" * 32, log_index=i,
                )
            )
            await apply_event(db, event)

        sub = (
            await db.execute(
                select(Subscription).where(Subscription.subscriber_address == address.lower())
            )
        ).scalar_one()
        # Latest event's periodEnd is authoritative (contract stacks the period).
        assert sub.current_period_end == datetime.fromtimestamp(now + 2 * MONTH, tz=UTC)
        payments = (
            await db.execute(
                select(SubscriptionPayment).where(
                    SubscriptionPayment.subscriber_address == address.lower()
                )
            )
        ).scalars()
        assert len(list(payments)) == 2  # one receipt per payment

    async def test_cancel_sets_flag_without_ending_coverage(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, address = await sign_in(client)
        now = int(datetime.now(UTC).timestamp())
        await apply_event(
            db,
            contract.decode_log(
                make_subscribed_log(
                    subscriber=address, plan_id=1, token="0x" + "cd" * 20,
                    amount_units=10_000_000, period_start=now, period_end=now + MONTH,
                    tx_hash="0x" + "b2" * 32,
                )
            ),
        )
        # A cancel event, constructed directly.
        cancel = contract.DecodedEvent(
            name="SubscriptionCancelled",
            args={"subscriber": address.lower(), "planId": 1, "expiresAt": now + MONTH},
            block_number=101, block_hash="0x" + "22" * 32,
            tx_hash="0x" + "b3" * 32, log_index=0,
        )
        assert await apply_event(db, cancel) == "applied"

        sub = (
            await db.execute(
                select(Subscription).where(Subscription.subscriber_address == address.lower())
            )
        ).scalar_one()
        assert sub.auto_renew_cancelled
        assert sub.is_active  # still covered
        assert sub.status == "cancelled"

    async def test_expired_subscription_reports_expired(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, address = await sign_in(client)
        past = int((datetime.now(UTC) - timedelta(days=60)).timestamp())
        await apply_event(
            db,
            contract.decode_log(
                make_subscribed_log(
                    subscriber=address, plan_id=1, token="0x" + "cd" * 20,
                    amount_units=10_000_000, period_start=past, period_end=past + MONTH,
                    tx_hash="0x" + "c4" * 32,
                )
            ),
        )
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.subscriber_address == address.lower())
            )
        ).scalar_one()
        assert not sub.is_active
        assert sub.status == "expired"
