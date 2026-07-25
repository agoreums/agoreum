"""API key model.

An API key is a long-lived credential for programmatic access. Like a refresh
token, only a SHA-256 hash of the secret is ever stored, so a database disclosure
yields nothing usable: the key is shown to its owner exactly once, at creation.

A key acts as its owner but is confined to its granted scopes (see `scopes.py`).
It carries an optional expiry and can be revoked at any time; authentication checks
both on every request.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.users.models import User


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # A human label chosen by the owner, so a key can be recognised and revoked
    # without exposing the secret ("CI pipeline", "local dev").
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    # The non-secret leading fragment of the key (e.g. "ak_ZuP1x8Qk"), shown in the
    # management UI so a specific key is identifiable at a glance. Safe to store and
    # display; it is not enough to authenticate with.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)

    # SHA-256 of the full key. Never the key itself.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Granted scopes, validated against the canonical set in the application.
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
    )

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > datetime.now(UTC)

    def __repr__(self) -> str:
        return f"<ApiKey {self.prefix}... user={self.user_id}>"
