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
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
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
