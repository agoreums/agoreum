"""Creator analytics tests.

The pure tests (path building, unavailable-views behavior) run anywhere. The
aggregation test needs a database and skips when none is reachable, exactly like
the other database-backed suites.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.enums import OrderStatus, PricingModel, ServiceStatus
from app.modules.agents.models import Agent
from app.modules.analytics import service as analytics
from app.modules.analytics import umami
from app.modules.orders.models import Order
from app.modules.organizations import service as org_service
from app.modules.services.models import Service
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


def test_path_patterns_cover_profile_and_services() -> None:
    patterns = umami.path_patterns(["acme", "atlas"])
    assert "%/agents/acme" in patterns
    assert "%/agents/acme/services/%" in patterns
    assert "%/agents/atlas" in patterns
    assert len(patterns) == 4


async def test_views_unavailable_when_umami_not_configured() -> None:
    # Default config has no Umami database, so views are None (unavailable), never
    # a fabricated zero.
    assert settings.analytics_views_enabled is False
    assert await umami.total_pageviews(["acme"], datetime.now(UTC)) is None
    assert await umami.daily_pageviews(["acme"], datetime.now(UTC)) is None


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(
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
        async with engine.connect() as probe:
            await probe.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"no database reachable: {type(exc).__name__}")
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def _addr() -> str:
    # A valid EVM address is 0x plus 40 hex characters (20 bytes).
    return "0x" + secrets.token_hex(20)


async def test_creator_analytics_counts_settled_orders(db: AsyncSession) -> None:
    tag = uuid.uuid4().hex[:8]
    owner = User(primary_address=_addr())
    buyer1 = User(primary_address=_addr())
    buyer2 = User(primary_address=_addr())
    db.add_all([owner, buyer1, buyer2])
    await db.flush()

    org = await org_service.ensure_personal_org(db, user=owner)
    agent = Agent(org_id=org.id, slug=f"acme-{tag}", name="Acme")
    db.add(agent)
    await db.flush()

    # Analytics counts orders by agent, not by service status, so a draft service
    # is enough and avoids the published-requires-timestamp constraint.
    svc = Service(
        agent_id=agent.id,
        slug=f"svc-{tag}",
        title="Service",
        pricing_model=PricingModel.FIXED,
        price=Decimal("10"),
        status=ServiceStatus.DRAFT,
    )
    db.add(svc)
    await db.flush()

    now = datetime.now(UTC)

    def order(buyer_id: uuid.UUID, ref: str) -> Order:
        return Order(
            reference=ref,
            buyer_id=buyer_id,
            provider_agent_id=agent.id,
            service_id=svc.id,
            status=OrderStatus.COMPLETED,
            quantity=1,
            unit_price=Decimal("10"),
            subtotal=Decimal("10"),
            platform_fee=Decimal("0.25"),
            total_amount=Decimal("10.25"),
            currency="USDC",
            platform_fee_bps=250,
            funded_at=now,
            completed_at=now,
        )

    # buyer1 buys twice (a repeat customer), buyer2 once.
    db.add_all(
        [
            order(buyer1.id, f"R{tag}A"),
            order(buyer1.id, f"R{tag}B"),
            order(buyer2.id, f"R{tag}C"),
        ]
    )
    await db.flush()

    result = await analytics.creator_analytics(db, user=owner, window_days=30)

    assert result.purchases == 3
    assert result.revenue == Decimal("30")
    assert result.currency == "USDC"
    assert result.repeat_customers == 1
    # No Umami database in the test environment: views and conversion are null.
    assert result.views is None
    assert result.conversion_rate is None


async def test_creator_with_no_agents_is_all_zero(db: AsyncSession) -> None:
    owner = User(primary_address=_addr())
    db.add(owner)
    await db.flush()

    result = await analytics.creator_analytics(db, user=owner, window_days=30)
    assert result.purchases == 0
    assert result.revenue == Decimal("0")
    assert result.repeat_customers == 0
    assert result.views is None
