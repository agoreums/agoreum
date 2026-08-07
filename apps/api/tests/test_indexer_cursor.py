"""Indexer position tracking.

The cursor decides where scanning resumes, so every bug here is an event that
never gets applied, an order that stays unfunded although the buyer paid, or a
release the provider never sees credited. These tests are about the ways a
position can be wrong rather than about the happy path.

No chain is needed: the cursor is pure database state.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.chain.indexer import (
    REORG_DEPTH,
    IndexerStartBlockUnknown,
    _save_cursor,
    resume_point,
)
from app.chain.models import IndexerCursor
from app.core.config import settings

pytestmark = pytest.mark.anyio

CONTRACT_A = "0x" + "aa" * 20
CONTRACT_B = "0x" + "bb" * 20
SEPOLIA = 84532
MAINNET = 8453


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


class TestFirstRun:
    async def test_refuses_to_start_when_no_deploy_block_is_configured(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        """Better a loud error than a silent scan from genesis.

        Defaulting to block 0 would appear to work while issuing tens of
        thousands of eth_getLogs calls against a chain 44 million blocks deep.
        """
        monkeypatch.setattr(settings, "ESCROW_DEPLOY_BLOCK", None)

        with pytest.raises(IndexerStartBlockUnknown):
            await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_A)

    async def test_starts_at_the_deploy_block(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "ESCROW_DEPLOY_BLOCK", 44_527_000)

        start = await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_A)

        assert start == 44_527_000


class TestResume:
    async def test_rewinds_by_the_reorg_depth(self, db: AsyncSession) -> None:
        """A stored position is not trusted to the block.

        Blocks the last scan covered may have been reorganised since. Re-applying
        an event is free, they are unique by transaction hash and log index, 
        whereas missing one is permanent.
        """
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=1_000_000)
        await db.flush()

        start = await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_A)

        assert start == 1_000_000 - REORG_DEPTH

    async def test_never_rewinds_below_genesis(self, db: AsyncSession) -> None:
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=10)
        await db.flush()

        assert await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_A) == 0

    async def test_a_stored_cursor_wins_over_the_deploy_block(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "ESCROW_DEPLOY_BLOCK", 500)
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=1_000_000)
        await db.flush()

        assert await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_A) != 500


class TestIsolation:
    """The cursor is keyed by contract and chain, and this is why."""

    async def test_a_new_contract_does_not_inherit_the_old_position(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        """Redeploying must not skip the new contract's early events.

        This is the expensive failure: a global cursor would carry the old
        contract's height forward, and every event the new contract emitted
        before that height, including funding, would never be applied. The
        money is real and nothing would report the gap.
        """
        monkeypatch.setattr(settings, "ESCROW_DEPLOY_BLOCK", 44_527_000)
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=44_600_000)
        await db.flush()

        start = await resume_point(db, chain_id=SEPOLIA, address=CONTRACT_B)

        assert start == 44_527_000

    async def test_the_same_contract_on_another_chain_is_tracked_separately(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "ESCROW_DEPLOY_BLOCK", 100)
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=44_600_000)
        await db.flush()

        assert await resume_point(db, chain_id=MAINNET, address=CONTRACT_A) == 100

    async def test_address_casing_does_not_create_a_second_cursor(
        self, db: AsyncSession
    ) -> None:
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A.lower(), block=900)
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A.upper().replace("0X", "0x"), block=1_500)
        await db.flush()

        rows = (
            await db.execute(
                sa.select(IndexerCursor).where(IndexerCursor.chain_id == SEPOLIA)
            )
        ).scalars().all()

        assert len(rows) == 1
        assert rows[0].last_scanned_block == 1_500


class TestMonotonicity:
    async def test_the_cursor_only_moves_forward(self, db: AsyncSession) -> None:
        """A deliberate rescan of an old range must not rewind everything after it.

        Re-indexing blocks 100-200 to repair a gap is a legitimate operation. If
        that reset the position to 200, every event between 200 and the real head
        would be rescanned on the next run at best, and the operator would have
        no idea the position had moved backwards.
        """
        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=1_000_000)
        await db.flush()

        await _save_cursor(db, chain_id=SEPOLIA, address=CONTRACT_A, block=200)
        await db.flush()

        row = (
            await db.execute(
                sa.select(IndexerCursor).where(
                    IndexerCursor.contract_address == CONTRACT_A.lower()
                )
            )
        ).scalar_one()

        assert row.last_scanned_block == 1_000_000


class TestConstraints:
    async def test_a_negative_block_is_refused_by_the_database(
        self, db: AsyncSession
    ) -> None:
        db.add(
            IndexerCursor(
                chain_id=SEPOLIA, contract_address=CONTRACT_A, last_scanned_block=-1
            )
        )

        with pytest.raises(sa.exc.IntegrityError):
            await db.flush()
