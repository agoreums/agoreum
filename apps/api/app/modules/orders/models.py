"""Orders, escrow, and on-chain transaction records.

This module holds the money path, and its design follows one rule: **off-chain
records never assert something the chain has not confirmed.**

Three concerns are deliberately kept in separate tables:

* `Order`      the commercial agreement between a buyer and an agent.
* `Escrow`     the state of funds held by the on-chain escrow contract.
* `ChainTransaction`  individual broadcast transactions and their confirmation state.

They are separate because they genuinely diverge. A funding transaction can be
broadcast (transaction exists) without being confirmed (escrow not yet funded)
while the order is still awaiting payment. Collapsing these into one status column
would force the code to lie about at least one of them.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import (
    DisputeResolution,
    EscrowStatus,
    OrderStatus,
    TransactionStatus,
    TransactionType,
    pg_enum,
)
from app.db.types import EthereumAddress, TokenAmount, TransactionHash

if TYPE_CHECKING:
    from app.modules.agents.models import Agent
    from app.modules.reputation.models import Review
    from app.modules.services.models import Service
    from app.modules.users.models import User


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"

    # Short human-quotable reference for support conversations, e.g. "AGO-7F3K2M".
    reference: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)

    buyer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # The agent providing the work. RESTRICT because an order is financial history.
    provider_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"),
        nullable=False,
        default=OrderStatus.PENDING_PAYMENT,
        server_default=OrderStatus.PENDING_PAYMENT.value,
    )

    # --- Commercial terms, frozen at order time -------------------------------
    # Captured as of purchase so a later price change on the service cannot alter
    # what an existing order is owed.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    # The two windows that decide when money moves, frozen for the same reason as
    # the price above. They were previously read from the live service whenever
    # payment instructions were built, so editing the service after an order
    # existed moved that order's deadlines. Shortening `auto_release_hours` is the
    # dangerous direction: it shrinks the window the buyer has to raise a dispute
    # before escrow releases to the provider.
    delivery_time_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_release_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="USDC"
    )
    # Basis points, recorded so a historical order shows the fee rate it was
    # actually charged rather than today's rate.
    platform_fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)

    # Buyer-supplied brief and the provider's delivered result.
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Lifecycle timestamps -------------------------------------------------
    funding_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When escrow auto-releases if the buyer neither accepts nor disputes.
    auto_release_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # A settled order that must not become standing. Set once, never cleared:
    # a database trigger refuses to lift an exclusion, to rewrite its timestamp,
    # or to rewrite its reason, so the one-way property does not depend on any
    # application code path being written correctly. See the migration
    # a1c3e5f7b9d2 for why that asymmetry is the whole point.
    #
    # This says nothing about the order itself. The payment happened, the escrow
    # settled, and the receipt still attests to it. Only reputation looks away.
    reputation_excluded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reputation_exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    buyer: Mapped[User] = relationship(back_populates="orders", foreign_keys=[buyer_id])
    provider_agent: Mapped[Agent] = relationship(foreign_keys=[provider_agent_id])
    service: Mapped[Service] = relationship(back_populates="orders")
    escrow: Mapped[Escrow | None] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    transactions: Mapped[list[ChainTransaction]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    review: Mapped[Review | None] = relationship(back_populates="order", uselist=False)
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderEvent.created_at",
    )

    __table_args__ = (
        CheckConstraint("quantity >= 1", name="quantity_at_least_one"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        CheckConstraint("subtotal > 0", name="subtotal_positive"),
        CheckConstraint("platform_fee >= 0", name="platform_fee_non_negative"),
        CheckConstraint("total_amount > 0", name="total_amount_positive"),
        CheckConstraint(
            "platform_fee_bps >= 0 AND platform_fee_bps <= 10000",
            name="platform_fee_bps_in_range",
        ),
        # The arithmetic must hold in the database, not merely in application code.
        CheckConstraint(
            "subtotal = unit_price * quantity", name="subtotal_matches_line"
        ),
        CheckConstraint(
            "total_amount = subtotal + platform_fee", name="total_matches_components"
        ),
        # A completed order must record when it completed, and vice versa.
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR funded_at IS NOT NULL",
            name="delivery_requires_funding",
        ),
        CheckConstraint(
            "completed_at IS NULL OR funded_at IS NOT NULL",
            name="completion_requires_funding",
        ),
        # An exclusion must carry its reason, or nobody can audit the decision
        # later, and the decision cannot be revisited. The one-way property
        # itself is a trigger rather than a constraint, because a CHECK sees only
        # the row it is given and this rule is about the transition.
        CheckConstraint(
            "(reputation_excluded_at IS NULL) = (reputation_exclusion_reason IS NULL)",
            name="reputation_exclusion_has_a_reason",
        ),
        # A buyer cannot purchase from an agent they own. Enforced in the service
        # layer (it requires a join); noted here as an intentional invariant.
        Index("ix_orders_buyer_id_created_at", "buyer_id", "created_at"),
        # Reputation filters on this for every agent it scores, and the excluded
        # set should stay tiny, so a partial index keeps that filter from
        # growing into a sequential scan as the table does.
        Index(
            "ix_orders_reputation_excluded",
            "provider_agent_id",
            postgresql_where=text("reputation_excluded_at IS NOT NULL"),
        ),
        Index(
            "ix_orders_provider_agent_id_status", "provider_agent_id", "status"
        ),
        Index("ix_orders_service_id", "service_id"),
        Index("ix_orders_status_created_at", "status", "created_at"),
        # Drives the auto-release worker: find delivered orders past their deadline.
        Index(
            "ix_orders_auto_release_due",
            "auto_release_at",
            postgresql_where=text("status = 'delivered'"),
        ),
        # Drives the funding-expiry worker.
        Index(
            "ix_orders_funding_deadline",
            "funding_deadline",
            postgresql_where=text("status = 'pending_payment'"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Order {self.reference} {self.status}>"


class Escrow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """On-chain escrow backing a single order.

    Every amount here reflects a confirmed on-chain state. Nothing in this table is
    written optimistically on broadcast: it is written when the chain confirms.
    """

    __tablename__ = "escrows"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    status: Mapped[EscrowStatus] = mapped_column(
        pg_enum(EscrowStatus, "escrow_status"),
        nullable=False,
        default=EscrowStatus.NONE,
        server_default=EscrowStatus.NONE.value,
    )

    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_address: Mapped[str | None] = mapped_column(EthereumAddress, nullable=True)
    # Identifier assigned by the escrow contract, read from its event log.
    onchain_escrow_id: Mapped[str | None] = mapped_column(String(78), nullable=True)

    token_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    token_symbol: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="USDC"
    )
    token_decimals: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="6"
    )

    # Human-readable decimal amounts. Base-unit integers are derived when building
    # transactions; these columns are what reporting and dashboards read.
    amount: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    released_amount: Mapped[Decimal] = mapped_column(
        TokenAmount, nullable=False, server_default="0"
    )
    refunded_amount: Mapped[Decimal] = mapped_column(
        TokenAmount, nullable=False, server_default="0"
    )
    fee_amount: Mapped[Decimal] = mapped_column(
        TokenAmount, nullable=False, server_default="0"
    )

    buyer_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    provider_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)

    funded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Dispute --------------------------------------------------------------
    disputed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_resolution: Mapped[DisputeResolution | None] = mapped_column(
        pg_enum(DisputeResolution, "dispute_resolution"),
        nullable=True,
    )
    dispute_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The provider's share, as decided. Recorded before the settlement is executed
    # so the on-chain result can always be compared against what was decided, and
    # so a settlement that differs is visible rather than merely surprising.
    #
    # Only this figure is stored. The contract derives the buyer's share as
    # amount - providerAmount and treats its own buyerAmount argument as a bounds
    # check, so keeping a second number here would create two sources of truth for
    # one decision, one of which the chain ignores.
    dispute_provider_amount: Mapped[Decimal | None] = mapped_column(
        TokenAmount, nullable=True
    )
    # Shown to the buyer and the provider, not published. An arbiter who cannot
    # explain a split to the party who lost should not have made it.
    dispute_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order: Mapped[Order] = relationship(back_populates="escrow")

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("released_amount >= 0", name="released_non_negative"),
        CheckConstraint("refunded_amount >= 0", name="refunded_non_negative"),
        CheckConstraint("fee_amount >= 0", name="fee_non_negative"),
        # The contract cannot pay out more than it holds. This is the single most
        # important invariant in the schema.
        CheckConstraint(
            "released_amount + refunded_amount <= amount",
            name="payouts_cannot_exceed_deposit",
        ),
        CheckConstraint("fee_amount <= amount", name="fee_within_deposit"),
        CheckConstraint("token_decimals BETWEEN 0 AND 36", name="token_decimals_sane"),
        CheckConstraint("chain_id > 0", name="chain_id_positive"),
        # Funded state requires evidence of funding.
        CheckConstraint(
            "status NOT IN ('funded','releasing','released','refunding','refunded','disputed')"
            " OR funded_at IS NOT NULL",
            name="funded_states_require_funded_at",
        ),
        CheckConstraint(
            "(status = 'released') = (released_at IS NOT NULL)",
            name="released_at_matches_status",
        ),
        CheckConstraint(
            "(dispute_resolution IS NULL) = (dispute_resolved_at IS NULL)",
            name="dispute_resolution_consistent",
        ),
        CheckConstraint(
            "dispute_resolved_at IS NULL OR disputed_at IS NOT NULL",
            name="resolution_requires_dispute",
        ),
        # One escrow record per on-chain escrow, per contract.
        UniqueConstraint(
            "contract_address", "onchain_escrow_id", name="contract_onchain_id"
        ),
        Index("ix_escrows_status", "status"),
        Index("ix_escrows_buyer_address", "buyer_address"),
        Index("ix_escrows_provider_address", "provider_address"),
    )

    def __repr__(self) -> str:
        return f"<Escrow order={self.order_id} {self.status}>"


class ChainTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single transaction broadcast to the chain, and its confirmation state.

    Rows are created when a transaction is broadcast and updated as it confirms.
    `REORGED` exists because confirmation is not final: a row that reached
    `CONFIRMED` can legitimately move backwards, and the system must be able to
    represent that rather than quietly keeping stale money state.
    """

    __tablename__ = "chain_transactions"

    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=True
    )
    escrow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("escrows.id", ondelete="CASCADE"), nullable=True
    )

    tx_hash: Mapped[str] = mapped_column(TransactionHash, nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)

    tx_type: Mapped[TransactionType] = mapped_column(
        pg_enum(TransactionType, "transaction_type"),
        nullable=False,
    )
    status: Mapped[TransactionStatus] = mapped_column(
        pg_enum(TransactionStatus, "transaction_status"),
        nullable=False,
        default=TransactionStatus.PENDING,
        server_default=TransactionStatus.PENDING.value,
    )

    from_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    to_address: Mapped[str | None] = mapped_column(EthereumAddress, nullable=True)
    # Token amount moved, when the transaction moves tokens.
    amount: Mapped[Decimal | None] = mapped_column(TokenAmount, nullable=True)
    token_address: Mapped[str | None] = mapped_column(EthereumAddress, nullable=True)

    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    gas_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_gas_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    broadcast_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Revert reason when the EVM rejected the transaction.
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    order: Mapped[Order | None] = relationship(back_populates="transactions")

    __table_args__ = (
        # A hash is unique per chain. Re-observing the same transaction must update
        # the existing row rather than insert a duplicate.
        UniqueConstraint("chain_id", "tx_hash", name="chain_tx_hash"),
        CheckConstraint("confirmations >= 0", name="confirmations_non_negative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "block_number IS NULL OR block_number >= 0", name="block_number_valid"
        ),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="confirmed_at_matches_status",
        ),
        # Anything the chain has included must carry its block.
        CheckConstraint(
            "status NOT IN ('confirmed','reverted') OR block_number IS NOT NULL",
            name="mined_requires_block_number",
        ),
        Index("ix_chain_transactions_order_id", "order_id"),
        Index("ix_chain_transactions_escrow_id", "escrow_id"),
        Index("ix_chain_transactions_status", "status"),
        # Drives the confirmation-watcher worker.
        Index(
            "ix_chain_transactions_pending",
            "chain_id",
            "broadcast_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_chain_transactions_block_number", "block_number"),
    )

    def __repr__(self) -> str:
        return f"<ChainTransaction {self.tx_hash} {self.status}>"


class OrderEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only audit trail of everything that happened to an order.

    Never updated or deleted. When a dispute needs adjudicating, this is the record
    of who did what and when.
    """

    __tablename__ = "order_events"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # NULL when the actor was the system (a worker, or an observed chain event).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    order: Mapped[Order] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_order_events_order_id_created_at", "order_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<OrderEvent {self.event_type} order={self.order_id}>"
