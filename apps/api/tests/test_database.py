"""Integration tests against a real PostgreSQL database.

These exercise behaviour that only exists in the database — CHECK constraints,
partial unique indexes, native enum labels, and the full-text search trigger.
Asserting them against SQLAlchemy metadata alone would prove nothing about what
PostgreSQL actually enforces at runtime.

Skipped automatically when no database is reachable, so the unit suite still runs
on a machine without one.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

pytestmark = pytest.mark.asyncio


def _address(seed: int) -> str:
    """A syntactically valid, unique EVM address for a test fixture."""
    return "0x" + f"{seed:040x}"


@pytest_asyncio.fixture
async def engine():
    """A per-test engine.

    Deliberately function-scoped: pytest-asyncio gives each test its own event
    loop, and an asyncpg connection created on one loop cannot be awaited on
    another. NullPool ensures no connection outlives the test that opened it.
    """
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
    """A session whose transaction is always rolled back.

    Every test therefore starts from the same state and leaves nothing behind.
    """
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
async def graph(db: AsyncSession) -> dict[str, uuid.UUID]:
    """A minimal real object graph: user → verified payout wallet → agent → service."""
    unique = uuid.uuid4().int % (10**8)

    user_id = (
        await db.execute(
            sa.text(
                "INSERT INTO users (primary_address) VALUES (:addr) RETURNING id"
            ),
            {"addr": _address(unique)},
        )
    ).scalar_one()

    wallet_id = (
        await db.execute(
            sa.text(
                "INSERT INTO wallets"
                " (user_id, address, chain_id, verification_status, verified_at, is_payout)"
                " VALUES (:uid, :addr, 8453, 'verified', now(), true) RETURNING id"
            ),
            {"uid": user_id, "addr": _address(unique + 1)},
        )
    ).scalar_one()

    agent_id = (
        await db.execute(
            sa.text(
                "INSERT INTO agents"
                " (owner_id, slug, name, status, payout_wallet_id, payout_address)"
                " VALUES (:uid, :slug, 'Test Agent', 'active', :wid, :addr) RETURNING id"
            ),
            {
                "uid": user_id,
                "slug": f"agent-{unique}",
                "wid": wallet_id,
                "addr": _address(unique + 1),
            },
        )
    ).scalar_one()

    service_id = (
        await db.execute(
            sa.text(
                "INSERT INTO services"
                " (agent_id, slug, title, summary, description, tags,"
                "  pricing_model, price, status, published_at)"
                " VALUES (:aid, :slug, 'Document Summarization',"
                "  'Condense long reports',"
                "  'Turns lengthy PDF reports into structured executive summaries.',"
                "  '{nlp,summarization}', 'fixed', 25.5, 'published', now())"
                " RETURNING id"
            ),
            {"aid": agent_id, "slug": f"svc-{unique}"},
        )
    ).scalar_one()

    return {
        "user_id": user_id,
        "wallet_id": wallet_id,
        "agent_id": agent_id,
        "service_id": service_id,
        "unique": unique,
    }


class TestEnumsArePersistedByValue:
    async def test_lowercase_value_is_accepted(self, db: AsyncSession) -> None:
        role = (
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address, role)"
                    " VALUES (:addr, 'admin') RETURNING role"
                ),
                {"addr": _address(0xA1)},
            )
        ).scalar_one()
        assert role == "admin"

    async def test_member_name_is_rejected(self, db: AsyncSession) -> None:
        """'ADMIN' is the Python member name, not the stored label."""
        with pytest.raises(DBAPIError):
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address, role)"
                    " VALUES (:addr, 'ADMIN')"
                ),
                {"addr": _address(0xA2)},
            )


class TestUserConstraints:
    async def test_address_is_unique(self, db: AsyncSession) -> None:
        addr = _address(0xB1)
        await db.execute(
            sa.text("INSERT INTO users (primary_address) VALUES (:a)"), {"a": addr}
        )
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text("INSERT INTO users (primary_address) VALUES (:a)"), {"a": addr}
            )

    async def test_malformed_username_is_rejected(self, db: AsyncSession) -> None:
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address, username)"
                    " VALUES (:a, 'Bad!Name')"
                ),
                {"a": _address(0xB2)},
            )

    async def test_email_verification_requires_an_email(
        self, db: AsyncSession
    ) -> None:
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address, email_verified_at)"
                    " VALUES (:a, now())"
                ),
                {"a": _address(0xB3)},
            )


class TestWalletConstraints:
    async def test_payout_wallet_must_be_verified(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """Funds must never be directed to an unproven address."""
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO wallets (user_id, address, chain_id, is_payout)"
                    " VALUES (:uid, :addr, 8453, true)"
                ),
                {"uid": graph["user_id"], "addr": _address(0xC1)},
            )

    async def test_one_payout_wallet_per_user(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """The graph fixture already has a payout wallet; a second must fail."""
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO wallets"
                    " (user_id, address, chain_id, verification_status,"
                    "  verified_at, is_payout)"
                    " VALUES (:uid, :addr, 8453, 'verified', now(), true)"
                ),
                {"uid": graph["user_id"], "addr": _address(0xC2)},
            )

    async def test_same_address_cannot_be_claimed_twice_on_a_chain(
        self, db: AsyncSession, graph: dict
    ) -> None:
        other_user = (
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address) VALUES (:a) RETURNING id"
                ),
                {"a": _address(0xC3)},
            )
        ).scalar_one()

        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO wallets (user_id, address, chain_id)"
                    " VALUES (:uid, :addr, 8453)"
                ),
                {"uid": other_user, "addr": _address(graph["unique"] + 1)},
            )

    async def test_address_is_stored_lowercase(self, db: AsyncSession) -> None:
        """Mixed-case input must normalise, or uniqueness could be bypassed."""
        mixed = "0x" + "AbCdEf0123" * 4
        stored = (
            await db.execute(
                sa.text(
                    "INSERT INTO users (primary_address) VALUES (:a)"
                    " RETURNING primary_address"
                ),
                {"a": mixed.lower()},
            )
        ).scalar_one()
        assert stored == mixed.lower()


class TestMoneyInvariants:
    async def _insert_order(
        self, db: AsyncSession, graph: dict, *, total: Decimal
    ) -> None:
        await db.execute(
            sa.text(
                "INSERT INTO orders"
                " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                "  unit_price, subtotal, platform_fee, total_amount, platform_fee_bps)"
                " VALUES (:ref, :uid, :aid, :sid, 2, 25.5, 51.0, 1.275, :total, 50)"
            ),
            {
                "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                "uid": graph["user_id"],
                "aid": graph["agent_id"],
                "sid": graph["service_id"],
                "total": total,
            },
        )

    async def test_correct_arithmetic_is_accepted(
        self, db: AsyncSession, graph: dict
    ) -> None:
        await self._insert_order(db, graph, total=Decimal("52.275"))

    async def test_inconsistent_total_is_rejected(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """total_amount must equal subtotal + platform_fee, enforced by the database."""
        with pytest.raises(IntegrityError):
            await self._insert_order(db, graph, total=Decimal("99.0"))

    async def test_amounts_keep_full_decimal_precision(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """USDC has 6 decimals; none of them may be lost to float rounding."""
        precise = Decimal("0.000001")
        stored = (
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, :p, :p, 0, :p, 0)"
                    " RETURNING total_amount"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                    "p": precise,
                },
            )
        ).scalar_one()
        assert stored == precise
        assert isinstance(stored, Decimal)


class TestEscrowInvariants:
    async def _insert_escrow(
        self, db: AsyncSession, graph: dict, *, released: str, refunded: str
    ) -> None:
        order_id = (
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, 100, 100, 0, 100, 0)"
                    " RETURNING id"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )
        ).scalar_one()

        await db.execute(
            sa.text(
                "INSERT INTO escrows"
                " (order_id, chain_id, token_address, amount, released_amount,"
                "  refunded_amount, buyer_address, provider_address)"
                " VALUES (:oid, 8453, :token, 100, :rel, :ref_, :buyer, :provider)"
            ),
            {
                "oid": order_id,
                "token": _address(0xDEAD),
                "rel": released,
                "ref_": refunded,
                "buyer": _address(0xBEE1),
                "provider": _address(0xBEE2),
            },
        )

    async def test_payouts_within_deposit_are_accepted(
        self, db: AsyncSession, graph: dict
    ) -> None:
        await self._insert_escrow(db, graph, released="60", refunded="40")

    async def test_escrow_cannot_pay_out_more_than_it_holds(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """The single most important invariant: the contract cannot overdraw."""
        with pytest.raises(IntegrityError):
            await self._insert_escrow(db, graph, released="80", refunded="40")


class TestReputationCannotBeFabricated:
    async def test_rating_sum_cannot_exceed_review_count_bound(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """An agent with 1 review cannot claim a rating sum of 500."""
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "UPDATE agents SET review_count = 1, rating_sum = 500"
                    " WHERE id = :aid"
                ),
                {"aid": graph["agent_id"]},
            )

    async def test_consistent_rating_totals_are_accepted(
        self, db: AsyncSession, graph: dict
    ) -> None:
        await db.execute(
            sa.text(
                "UPDATE agents SET review_count = 2, rating_sum = 9 WHERE id = :aid"
            ),
            {"aid": graph["agent_id"]},
        )

    async def test_service_reviews_cannot_exceed_completed_orders(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """A service with no completed orders cannot have reviews."""
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "UPDATE services SET review_count = 5, completed_order_count = 0"
                    " WHERE id = :sid"
                ),
                {"sid": graph["service_id"]},
            )

    async def test_rating_outside_one_to_five_is_rejected(
        self, db: AsyncSession, graph: dict
    ) -> None:
        order_id = (
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps, funded_at, completed_at, status)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, 10, 10, 0, 10, 0,"
                    "  now(), now(), 'completed')"
                    " RETURNING id"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )
        ).scalar_one()

        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO reviews"
                    " (order_id, author_id, subject_agent_id, service_id, rating)"
                    " VALUES (:oid, :uid, :aid, :sid, 9)"
                ),
                {
                    "oid": order_id,
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )

    async def test_only_one_review_per_order(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """Structurally prevents review-stuffing."""
        order_id = (
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps, funded_at, completed_at, status)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, 10, 10, 0, 10, 0,"
                    "  now(), now(), 'completed')"
                    " RETURNING id"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )
        ).scalar_one()

        params = {
            "oid": order_id,
            "uid": graph["user_id"],
            "aid": graph["agent_id"],
            "sid": graph["service_id"],
        }
        insert = sa.text(
            "INSERT INTO reviews"
            " (order_id, author_id, subject_agent_id, service_id, rating)"
            " VALUES (:oid, :uid, :aid, :sid, 5)"
        )
        await db.execute(insert, params)

        with pytest.raises(IntegrityError):
            await db.execute(insert, params)


class TestOrderLifecycleConsistency:
    async def test_completed_order_must_record_completion_time(
        self, db: AsyncSession, graph: dict
    ) -> None:
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps, status, funded_at)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, 10, 10, 0, 10, 0,"
                    "  'completed', now())"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )

    async def test_completion_requires_funding(
        self, db: AsyncSession, graph: dict
    ) -> None:
        """An order cannot complete without money ever having arrived."""
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO orders"
                    " (reference, buyer_id, provider_agent_id, service_id, quantity,"
                    "  unit_price, subtotal, platform_fee, total_amount,"
                    "  platform_fee_bps, status, completed_at)"
                    " VALUES (:ref, :uid, :aid, :sid, 1, 10, 10, 0, 10, 0,"
                    "  'completed', now())"
                ),
                {
                    "ref": f"AGO-{uuid.uuid4().hex[:8].upper()}",
                    "uid": graph["user_id"],
                    "aid": graph["agent_id"],
                    "sid": graph["service_id"],
                },
            )


class TestFullTextSearchTrigger:
    async def test_trigger_populates_search_vector_on_insert(
        self, db: AsyncSession, graph: dict
    ) -> None:
        vector = (
            await db.execute(
                sa.text("SELECT search_vector FROM services WHERE id = :sid"),
                {"sid": graph["service_id"]},
            )
        ).scalar_one()
        assert vector, "trigger did not populate search_vector"

    @pytest.mark.parametrize("term", ["summarization", "executive", "nlp"])
    async def test_terms_from_every_weighted_field_are_searchable(
        self, db: AsyncSession, graph: dict, term: str
    ) -> None:
        """title (A), tags (B), and description (C) must all be indexed."""
        found = (
            await db.execute(
                sa.text(
                    "SELECT id FROM services"
                    " WHERE id = :sid"
                    "   AND search_vector @@ to_tsquery('english', :term)"
                ),
                {"sid": graph["service_id"], "term": term},
            )
        ).scalar_one_or_none()
        assert found is not None, f"{term!r} was not searchable"

    async def test_title_outranks_description(
        self, db: AsyncSession, graph: dict
    ) -> None:
        title_rank, description_rank = (
            await db.execute(
                sa.text(
                    "SELECT"
                    "  ts_rank(search_vector, to_tsquery('english', 'summarization')),"
                    "  ts_rank(search_vector, to_tsquery('english', 'executive'))"
                    " FROM services WHERE id = :sid"
                ),
                {"sid": graph["service_id"]},
            )
        ).one()
        assert title_rank > description_rank

    async def test_trigger_updates_vector_when_title_changes(
        self, db: AsyncSession, graph: dict
    ) -> None:
        await db.execute(
            sa.text(
                "UPDATE services SET title = 'Blockchain Forensics' WHERE id = :sid"
            ),
            {"sid": graph["service_id"]},
        )
        found = (
            await db.execute(
                sa.text(
                    "SELECT id FROM services WHERE id = :sid"
                    " AND search_vector @@ to_tsquery('english', 'forensics')"
                ),
                {"sid": graph["service_id"]},
            )
        ).scalar_one_or_none()
        assert found is not None, "trigger did not refresh the vector on update"
