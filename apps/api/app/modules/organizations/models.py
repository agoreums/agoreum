"""Organizations and memberships.

An organization owns agents (and therefore their services, payouts, and provider
side of orders). Every user has a `personal` org, created on first sign-in, so a
solo creator behaves exactly as before; a `team` org is shared by many members.

Membership carries a role that answers what a member may do within that org. Money
and security sensitive actions require admin or owner; day-to-day building is open
to members. Wallets stay owned by individual users: an agent's payout still points
at a wallet a real member proved they control, so nothing custodial is introduced.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import OrgKind, OrgRole, pg_enum
from app.db.types import LowercaseString

if TYPE_CHECKING:
    from app.modules.agents.models import Agent
    from app.modules.users.models import User


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    # Public handle, case-insensitively unique across every org (personal and team).
    slug: Mapped[str] = mapped_column(LowercaseString(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)

    kind: Mapped[OrgKind] = mapped_column(
        pg_enum(OrgKind, "org_kind"),
        nullable=False,
        default=OrgKind.TEAM,
        server_default=OrgKind.TEAM.value,
    )

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", lazy="selectin"
    )
    agents: Mapped[list[Agent]] = relationship(back_populates="organization")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization {self.slug} ({self.kind})>"


class OrganizationMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrgRole] = mapped_column(
        pg_enum(OrgRole, "org_role"),
        nullable=False,
        default=OrgRole.MEMBER,
        server_default=OrgRole.MEMBER.value,
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="org_memberships")

    __table_args__ = (
        # A user holds at most one membership per org.
        UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
        Index("ix_org_memberships_user_id", "user_id"),
        Index("ix_org_memberships_org_id", "org_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrganizationMembership org={self.org_id} user={self.user_id} {self.role}>"

class OrganizationInvitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A pending offer of membership, which the invitee has to accept.

    Membership used to be granted directly: an owner named an address and that
    account was in the organization, without ever agreeing to it. That is a
    consent problem rather than a cosmetic one, because membership decides who
    receives notifications about an organization's orders, and it let anyone
    attach an unwilling account to a name they had no association with.

    Rows are kept after they are resolved rather than deleted, so there is a
    record of who invited whom and what came of it. `responded_at` with
    `accepted` is the outcome; both null means still pending.
    """

    __tablename__ = "organization_invitations"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The invitee must already have an account, since membership is keyed on a
    # user. Inviting an address that has never signed in would mean holding an
    # offer against something that may never exist.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[OrgRole] = mapped_column(
        pg_enum(OrgRole, "org_role"), nullable=False, default=OrgRole.MEMBER
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    organization: Mapped[Organization] = relationship()

    __table_args__ = (
        # One live invitation per person per organization. Resolved rows are
        # excluded so the same person can be re-invited after declining.
        Index(
            "uq_org_invitation_pending",
            "org_id",
            "user_id",
            unique=True,
            postgresql_where=text("responded_at IS NULL"),
        ),
        Index("ix_org_invitations_user_id", "user_id"),
        CheckConstraint(
            "(responded_at IS NULL) = (accepted IS NULL)",
            name="response_is_complete",
        ),
    )
