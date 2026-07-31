"""Applying a chain event to an order loaded fresh from the database.

This is the path that runs in production: the indexer is its own process, so it
loads each order in a new session with nothing in the identity map. The apply
code reads `order.escrow` and `order.buyer`, which are lazy relationships, if
the query does not eager-load them, the access is synchronous IO inside async
SQLAlchemy and raises MissingGreenlet on the very first real event.

A local-Anvil test never caught this because it created the order in the same
session the indexer then used, so the relationships were already loaded. Only a
fresh-session apply exercises the real path. These tests use a committed order
reloaded in a separate session, exactly as production does.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.chain import escrow as contract
from app.chain.indexer import _apply_event
from app.core.config import settings
from app.db.enums import AgentStatus, OrderStatus, PricingModel, ServiceStatus
from app.modules.agents.models import Agent
from app.modules.orders.models import Order
from app.modules.services.models import Service
from app.modules.users.models import User, Wallet

pytestmark = pytest.mark.anyio

BUYER = "0x" + "11" * 20
PROVIDER = "0x" + "22" * 20
TOKEN = settings.usdc_address.lower()
ESCROW_ADDRESS = "0x" + "ab" * 20


@pytest.fixture(autouse=True)
def _configure_escrow(monkeypatch):
    """Give the apply path a contract address to record.

    Applying an EscrowCreated event writes `contract.contract_address()` onto the
    new Escrow row, and that raises EscrowNotConfiguredError when
    ESCROW_CONTRACT_ADDRESS is unset, which it is in CI, where no contract is
    deployed. The test is about the database apply logic, not any specific
    deployment, so it configures a deterministic address itself rather than
    depending on the environment. No chain call is made; contract_address() only
    reads configuration.
    """
    monkeypatch.setattr(settings, "ESCROW_CONTRACT_ADDRESS", ESCROW_ADDRESS)


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
async def sessionmaker(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def _make_committed_order(sm) -> uuid.UUID:
    """Create a full order graph and commit it, then forget it.

    Returns only the id, so the caller must reload it, which is the whole point.
    """
    async with sm() as s:
        buyer = User(primary_address=BUYER)
        provider = User(primary_address=PROVIDER)
        s.add_all([buyer, provider])
        await s.flush()
        wallet = Wallet(
            user_id=provider.id, address=PROVIDER, chain_id=settings.CHAIN_ID,
            is_payout=True, verification_status="verified",
            verified_at=datetime.now(UTC),
        )
        s.add(wallet)
        await s.flush()
        tag = uuid.uuid4().hex[:8]
        agent = Agent(
            owner_id=provider.id, slug=f"apply-{tag}", name="Apply Test",
            status=AgentStatus.ACTIVE, payout_wallet_id=wallet.id,
            payout_address=PROVIDER,
        )
        s.add(agent)
        await s.flush()
        svc = Service(
            agent_id=agent.id, slug=f"apply-svc-{tag}", title="Apply Service",
            status=ServiceStatus.PUBLISHED, pricing_model=PricingModel.FIXED,
            price=Decimal("1.000000"), price_currency="USDC", min_quantity=1,
            delivery_time_hours=1, auto_release_hours=1,
            published_at=datetime.now(UTC),
        )
        s.add(svc)
        await s.flush()
        order = Order(
            reference=uuid.uuid4().hex[:12].upper(),
            buyer_id=buyer.id, provider_agent_id=agent.id, service_id=svc.id,
            status=OrderStatus.PENDING_PAYMENT, quantity=1,
            unit_price=Decimal("1.000000"), subtotal=Decimal("1.000000"),
            platform_fee=Decimal("0.025000"), total_amount=Decimal("1.025000"),
            currency="USDC", platform_fee_bps=250,
        )
        s.add(order)
        await s.flush()
        order_id = order.id
        await s.commit()
    return order_id


def _created_event(order_id: uuid.UUID) -> contract.DecodedEvent:
    return contract.DecodedEvent(
        name="EscrowCreated",
        escrow_id=contract.escrow_id_for_order(str(order_id)),
        args={
            "buyer": BUYER,
            "provider": PROVIDER,
            "token": TOKEN,
            "amount": 1_025_000,
        },
        block_number=1_000,
        block_hash="0x" + "ab" * 32,
        tx_hash="0x" + "cd" * 32,
        log_index=0,
    )


async def _cleanup(sm, order_id):
    async with sm() as s:
        order = (
            await s.execute(sa.select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if order is None:
            return
        agent_id = order.provider_agent_id
        buyer_id = order.buyer_id
        agent = (await s.execute(sa.select(Agent).where(Agent.id == agent_id))).scalar_one()
        owner_id = agent.owner_id
        await s.execute(sa.delete(Order).where(Order.id == order_id))
        await s.execute(sa.delete(Service).where(Service.agent_id == agent_id))
        await s.execute(sa.delete(Agent).where(Agent.id == agent_id))
        await s.execute(sa.delete(Wallet).where(Wallet.user_id == owner_id))
        await s.execute(sa.delete(User).where(User.id.in_([owner_id, buyer_id])))
        await s.commit()


class TestApplyToFreshOrder:
    async def test_escrow_created_funds_an_order_loaded_in_a_new_session(
        self, sessionmaker
    ) -> None:
        """The regression: this raised MissingGreenlet before the eager-load fix.

        The order is created and committed in one session, then the event is
        applied in a completely separate one, so `order.escrow` (None here) and
        `order.buyer.primary_address` are cold and must be eager-loaded, not
        lazily fetched.
        """
        order_id = await _make_committed_order(sessionmaker)
        try:
            async with sessionmaker() as s:
                outcome = await _apply_event(s, _created_event(order_id))
                await s.commit()
            assert outcome == "applied"

            async with sessionmaker() as s:
                order = (
                    await s.execute(sa.select(Order).where(Order.id == order_id))
                ).scalar_one()
                assert order.status == OrderStatus.FUNDED
                assert order.funded_at is not None
        finally:
            await _cleanup(sessionmaker, order_id)

    async def test_reapplying_the_same_event_is_idempotent(self, sessionmaker) -> None:
        """A second scan of the same block must not double-apply."""
        order_id = await _make_committed_order(sessionmaker)
        try:
            event = _created_event(order_id)
            async with sessionmaker() as s:
                assert await _apply_event(s, event) == "applied"
                await s.commit()
            async with sessionmaker() as s:
                assert await _apply_event(s, event) == "duplicate"
                await s.commit()
        finally:
            await _cleanup(sessionmaker, order_id)

    async def test_an_event_for_an_unknown_order_is_skipped_not_invented(
        self, sessionmaker
    ) -> None:
        """An escrow with no matching order is logged and skipped, never faked."""
        event = _created_event(uuid.uuid4())
        async with sessionmaker() as s:
            assert await _apply_event(s, event) == "skipped"
            await s.commit()
