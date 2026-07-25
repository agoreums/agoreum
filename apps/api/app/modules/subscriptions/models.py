"""Subscription models.

Three tables, and a strict rule about which is authoritative:

* `subscription_plans` is the off-chain catalogue. It mirrors the on-chain plans
  and carries the presentation a contract has no business holding (name, blurb).
  The `plan_id` is the on-chain identifier, so the two are always reconcilable.

* `subscriptions` is a *projection of the chain*, never a source of truth. Its
  coverage window is only ever written by the indexer applying a confirmed
  `Subscribed` event. Nothing in the application marks a subscription active; a
  subscription is active because a real payment happened.

* `subscription_payments` is the on-chain payment history — one row per confirmed
  `Subscribed` event, keyed by `(tx_hash, log_index)` so re-scanning applies
  nothing twice. This is the receipt trail.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import SubscriptionInterval, pg_enum
from app.db.types import EthereumAddress, TokenAmount, TransactionHash

if TYPE_CHECKING:
    from app.modules.users.models import User


class SubscriptionPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscription_plans"

    # The on-chain plan identifier. Governance chooses it so the catalogue and the
    # contract can be reconciled without a mapping that could drift.
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # The entitlement this plan grants, e.g. "pro" or "organization". Free-form so
    # the product can add tiers without a migration.
    tier: Mapped[str] = mapped_column(String(40), nullable=False)
    interval: Mapped[SubscriptionInterval] = mapped_column(
        pg_enum(SubscriptionInterval, "subscription_interval"), nullable=False
    )

    token_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(12), nullable=False, server_default="USDC")
    token_decimals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="6")
    price: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    period_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Whether the plan is offered. Mirrors the on-chain `active` flag; a deactivated
    # plan still honours existing coverage but takes no new subscriptions.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    def __repr__(self) -> str:
        return f"<SubscriptionPlan {self.plan_id} {self.tier}>"


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    # The wallet that paid, which is the on-chain key alongside plan_id. Coverage
    # belongs to the address; the user link is resolved from a verified wallet.
    subscriber_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Resolved when the paying wallet is a verified wallet of a known user. Null
    # for a payment from an address the platform does not yet know.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # The subscriber signalled (on-chain) they will not renew. Coverage still runs
    # to current_period_end; this only suppresses renewal prompts.
    auto_renew_cancelled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    last_payment_tx: Mapped[str | None] = mapped_column(TransactionHash, nullable=True)

    user: Mapped[User | None] = relationship()

    __table_args__ = (
        UniqueConstraint("subscriber_address", "plan_id", name="subscriber_plan"),
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_current_period_end", "current_period_end"),
    )

    @property
    def is_active(self) -> bool:
        return self.current_period_end > datetime.now(UTC)

    @property
    def status(self) -> str:
        if self.is_active:
            return "cancelled" if self.auto_renew_cancelled else "active"
        return "expired"

    def __repr__(self) -> str:
        return f"<Subscription {self.subscriber_address} plan={self.plan_id}>"


class SubscriptionPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One confirmed on-chain payment. The receipt trail; never fabricated."""

    __tablename__ = "subscription_payments"

    tx_hash: Mapped[str] = mapped_column(TransactionHash, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)

    subscriber_address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    amount: Mapped[Decimal] = mapped_column(TokenAmount, nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(12), nullable=False, server_default="USDC")

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(String(66), nullable=False)

    __table_args__ = (
        # On-chain uniqueness: a log is identified by its transaction and index.
        # This is what makes re-scanning a block range idempotent.
        UniqueConstraint("tx_hash", "log_index", name="uq_subscription_payment_log"),
        Index("ix_subscription_payments_subscriber", "subscriber_address"),
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPayment {self.tx_hash}:{self.log_index}>"
