"""User and wallet models.

A *user* is a human principal. Identity is anchored to a wallet address rather than
to an email/password pair: the address that authenticates is the address that gets
paid, which removes an entire class of account-takeover and payout-redirection risk.

Email is optional and used only for notifications.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import (
    AccountStatus,
    UserRole,
    WalletProvider,
    WalletVerificationStatus,
    pg_enum,
)
from app.db.types import EthereumAddress, LowercaseString

if TYPE_CHECKING:
    from app.modules.notifications.models import Notification, NotificationPreference
    from app.modules.orders.models import Order
    from app.modules.organizations.models import OrganizationMembership
    from app.modules.reputation.models import Review


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    # The wallet this account authenticates with. Immutable in practice: changing
    # it would transfer the identity, so a new address means a new account.
    primary_address: Mapped[str] = mapped_column(
        EthereumAddress, nullable=False, unique=True
    )

    # Public-facing handle. Case-insensitively unique so `Alice` cannot squat on
    # a visually identical `alice`.
    username: Mapped[str | None] = mapped_column(
        LowercaseString(32), nullable=True, unique=True
    )
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(600), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Optional. Only used for notification delivery, never for authentication.
    email: Mapped[str | None] = mapped_column(
        LowercaseString(320), nullable=True, unique=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus, "account_status"),
        nullable=False,
        default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE.value,
    )

    preferred_locale: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="en"
    )

    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    wallets: Mapped[list[Wallet]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="buyer", foreign_keys="Order.buyer_id"
    )
    reviews_written: Mapped[list[Review]] = relationship(
        back_populates="author", foreign_keys="Review.author_id"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notification_preferences: Mapped[list[NotificationPreference]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    org_memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "username IS NULL OR username ~ '^[a-z0-9][a-z0-9_-]{2,31}$'",
            name="username_format",
        ),
        CheckConstraint(
            "email IS NULL OR position('@' in email) > 1",
            name="email_shape",
        ),
        # Verification cannot exist without an address to verify.
        CheckConstraint(
            "email_verified_at IS NULL OR email IS NOT NULL",
            name="email_verified_requires_email",
        ),
        Index("ix_users_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.primary_address}>"


class Wallet(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A wallet address a user has proven control of.

    The platform never stores private keys, seed phrases, or any material from
    which a key could be derived. This table holds public addresses and the
    evidence that someone signed with them.
    """

    __tablename__ = "wallets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    chain_id: Mapped[int] = mapped_column(nullable=False, server_default="8453")

    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[WalletProvider] = mapped_column(
        pg_enum(WalletProvider, "wallet_provider"),
        nullable=False,
        default=WalletProvider.OTHER,
        server_default=WalletProvider.OTHER.value,
    )
    verification_status: Mapped[WalletVerificationStatus] = mapped_column(
        pg_enum(WalletVerificationStatus, "wallet_verification_status"),
        nullable=False,
        default=WalletVerificationStatus.UNVERIFIED,
        server_default=WalletVerificationStatus.UNVERIFIED.value,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The exact SIWE message that was signed, retained as evidence of the proof.
    verification_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Where earnings are sent. Exactly one per user, enforced by a partial index.
    is_payout: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    user: Mapped[User] = relationship(back_populates="wallets")

    __table_args__ = (
        # The same address may exist on different chains, but only once per chain
        # across the whole platform, two accounts cannot claim one wallet.
        UniqueConstraint("address", "chain_id", name="address_chain"),
        # A payout wallet must be verified; otherwise funds could be directed to
        # an address nobody has proven they control.
        CheckConstraint(
            "NOT is_payout OR verification_status = 'verified'",
            name="payout_requires_verification",
        ),
        CheckConstraint(
            "(verification_status = 'verified') = (verified_at IS NOT NULL)",
            name="verified_at_matches_status",
        ),
        CheckConstraint("chain_id > 0", name="chain_id_positive"),
        # At most one payout wallet per user. A partial unique index expresses this
        # exactly: rows with is_payout = false are not constrained at all.
        Index(
            "uq_wallets_one_payout_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_payout"),
        ),
        Index("ix_wallets_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Wallet {self.address} chain={self.chain_id}>"


class Session(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A refresh-token session established by a successful SIWE authentication.

    Only a hash of the refresh token is stored, so a database disclosure does not
    hand an attacker usable session credentials.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # SHA-256 of the refresh token. Never the token itself.
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    # The address that signed in, which may be any of the user's verified wallets.
    address: Mapped[str] = mapped_column(EthereumAddress, nullable=False)
    chain_id: Mapped[int] = mapped_column(nullable=False)

    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_id_expires_at", "user_id", "expires_at"),
        # Supports the periodic purge of dead sessions.
        Index("ix_sessions_expires_at", "expires_at"),
    )

    @property
    def is_active(self) -> bool:

        now = datetime.now(UTC)
        return self.revoked_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"<Session {self.id} user={self.user_id}>"


class SiweNonce(Base, UUIDPrimaryKeyMixin):
    """A single-use nonce issued for a SIWE challenge.

    Persisted rather than held in memory so that replay protection survives a
    restart and holds across multiple API replicas. Consumed exactly once.
    """

    __tablename__ = "siwe_nonces"

    nonce: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(EthereumAddress, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_siwe_nonces_expires_at", "expires_at"),)

    def __repr__(self) -> str:
        return f"<SiweNonce {self.nonce[:8]}...>"


class EmailVerificationToken(Base, UUIDPrimaryKeyMixin):
    """A single-use token proving control of an email address.

    Until an address is proven, it is only a string somebody typed. Without this,
    anyone could set another person's address on their own profile and have the
    platform send mail there, which is an open relay for harassment wearing the
    sender reputation of the domain.

    Only the SHA-256 of the token is stored. A leaked database backup should not
    hand out working verification links, and the same reasoning already applies to
    refresh tokens elsewhere in this schema.

    `email` is recorded alongside the token rather than read from the user at
    confirmation time. A token proves control of *the address it was sent to*, so
    if the profile address changes between issue and confirmation the token must
    not silently verify the new one.
    """

    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The address this token was issued for. Verification applies to this value
    # and no other.
    email: Mapped[str] = mapped_column(LowercaseString(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_email_verification_tokens_user_id", "user_id"),
        Index("ix_email_verification_tokens_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<EmailVerificationToken user={self.user_id} used={self.consumed_at is not None}>"
