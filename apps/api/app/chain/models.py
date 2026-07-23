"""Indexer progress state.

The indexer is idempotent, so a cursor is not what makes it *correct* — it is
what makes it *affordable*. Without a persisted position every run would have
to rescan from the contract's deployment block, which on a chain 44 million
blocks deep is thousands of `eth_getLogs` calls to rediscover events already
applied.

The cursor is keyed by `(chain_id, contract_address)` rather than being a
single global row. Two situations make that necessary:

* Redeploying the contract produces a new address. A global cursor would carry
  the old contract's height forward and the new contract's early events —
  including funding — would be skipped entirely, silently.
* The same database restored against a different network must not inherit a
  height that means nothing there.

Both failure modes lose money quietly, which is the worst way to lose it.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import EthereumAddress


class IndexerCursor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How far the indexer has scanned for one contract on one chain."""

    __tablename__ = "indexer_cursors"

    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)

    # The last block whose logs have been applied. The next scan resumes at
    # this height rather than the one after it: re-reading a block is free
    # (events are unique by transaction hash and log index) whereas skipping
    # one loses an event permanently.
    last_scanned_block: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "chain_id", "contract_address", name="uq_indexer_cursors_chain_contract"
        ),
        CheckConstraint(
            "last_scanned_block >= 0", name="indexer_cursors_block_non_negative"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<IndexerCursor chain={self.chain_id} "
            f"contract={self.contract_address} block={self.last_scanned_block}>"
        )
