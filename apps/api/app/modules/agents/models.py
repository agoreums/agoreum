"""Agent identity models.

An *agent* is a non-human principal: an AI system or software service that can
publish services, be discovered, transact, and accumulate reputation.

Every agent is owned by a user, who is accountable for it, and settles to a wallet
whose control has been cryptographically proven. An agent can therefore never be
paid to an address nobody has demonstrated ownership of.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
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
from app.db.enums import AgentStatus, AgentVerificationTier, pg_enum
from app.db.types import EthereumAddress, LowercaseString

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.reputation.models import ReputationSnapshot
    from app.modules.services.models import Service


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    # The organization that owns this agent. Every user has a personal org, so a
    # solo creator's agents sit in their own org; a team's agents are shared.
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )

    # URL-safe public identifier, e.g. /agents/atlas-research.
    slug: Mapped[str] = mapped_column(LowercaseString(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    tagline: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[AgentStatus] = mapped_column(
        pg_enum(AgentStatus, "agent_status"),
        nullable=False,
        default=AgentStatus.DRAFT,
        server_default=AgentStatus.DRAFT.value,
    )
    verification_tier: Mapped[AgentVerificationTier] = mapped_column(
        pg_enum(AgentVerificationTier, "agent_verification_tier"),
        nullable=False,
        default=AgentVerificationTier.UNVERIFIED,
        server_default=AgentVerificationTier.UNVERIFIED.value,
    )

    # Where this agent's earnings settle. Must be a verified wallet; enforced in
    # the service layer against wallets.verification_status and by FK here.
    payout_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=True
    )
    # Denormalised for read paths that resolve a payout target without a join.
    # Kept in sync with payout_wallet_id by the service layer.
    payout_address: Mapped[str | None] = mapped_column(EthereumAddress, nullable=True)

    # Optional homepage; domain verification (if any) is proven against this host.
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verified_domain: Mapped[str | None] = mapped_column(
        LowercaseString(253), nullable=True
    )
    domain_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # A GitHub account or organisation the operator has proven control of, by
    # publishing a challenge token in a public gist under that account. Independent
    # of the domain tier: it is a separate trust signal, not a tier elevation.
    verified_github: Mapped[str | None] = mapped_column(
        LowercaseString(39), nullable=True  # GitHub logins are at most 39 chars
    )
    github_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Machine-readable capability descriptors used by discovery and by other agents
    # negotiating work. Free-form by design: capability vocabularies will evolve
    # faster than migrations should.
    capabilities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Endpoint another agent can call to initiate work. Never invoked without an
    # order; recorded here as part of the agent's published interface.
    api_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Reputation counters --------------------------------------------------
    # Maintained transactionally as orders reach COMPLETED and as reviews are
    # published. These are caches of real activity, never seeded and never
    # incremented by anything other than a genuine completed order.
    completed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cancelled_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    disputed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # Sum of published review ratings. Kept as a sum (not an average) so the mean
    # can be recomputed exactly when a review is withdrawn.
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    organization: Mapped[Organization] = relationship(back_populates="agents")
    services: Mapped[list[Service]] = relationship(back_populates="agent")
    reputation_snapshots: Mapped[list[ReputationSnapshot]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{1,63}$'", name="slug_format"
        ),
        CheckConstraint("completed_orders >= 0", name="completed_orders_non_negative"),
        CheckConstraint("cancelled_orders >= 0", name="cancelled_orders_non_negative"),
        CheckConstraint("disputed_orders >= 0", name="disputed_orders_non_negative"),
        CheckConstraint("review_count >= 0", name="review_count_non_negative"),
        # Ratings are 1..5, so the sum is bounded by the review count. This makes
        # a fabricated rating_sum impossible to store.
        CheckConstraint(
            "rating_sum >= 0 AND rating_sum <= review_count * 5",
            name="rating_sum_within_bounds",
        ),
        # A payout address may only be recorded alongside the wallet it came from.
        CheckConstraint(
            "(payout_wallet_id IS NULL) = (payout_address IS NULL)",
            name="payout_address_matches_wallet",
        ),
        CheckConstraint(
            "(verified_domain IS NULL) = (domain_verified_at IS NULL)",
            name="domain_verification_consistent",
        ),
        CheckConstraint(
            "(verified_github IS NULL) = (github_verified_at IS NULL)",
            name="github_verification_consistent",
        ),
        # A tier above unverified requires the corresponding proof to exist.
        CheckConstraint(
            "verification_tier = 'unverified' OR verified_domain IS NOT NULL",
            name="verified_tier_requires_domain_proof",
        ),
        # An agent cannot be publicly listed without a proven payout target.
        CheckConstraint(
            "status <> 'active' OR payout_wallet_id IS NOT NULL",
            name="active_agent_requires_payout_wallet",
        ),
        Index("ix_agents_org_id", "org_id"),
        Index("ix_agents_status_published_at", "status", "published_at"),
        Index("ix_agents_capabilities", "capabilities", postgresql_using="gin"),
    )

    @property
    def average_rating(self) -> float | None:
        """Mean review rating, or None when the agent has never been reviewed.

        Returning None rather than 0.0 matters: an unrated agent is unknown, not bad.
        """
        if self.review_count == 0:
            return None
        return round(self.rating_sum / self.review_count, 2)

    def __repr__(self) -> str:
        return f"<Agent {self.slug}>"


class AgentDomainChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An outstanding proof-of-domain-control challenge.

    The agent operator publishes the token at a DNS TXT record or well-known path;
    the platform fetches it and only then records the domain as verified.
    """

    __tablename__ = "agent_domain_challenges"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(LowercaseString(253), nullable=False)
    token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "domain", name="agent_domain"),
        CheckConstraint("method IN ('dns_txt', 'well_known')", name="method_supported"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        Index("ix_agent_domain_challenges_agent_id", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentDomainChallenge {self.domain}>"


class AgentGithubChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An outstanding proof-of-GitHub-control challenge.

    The operator publishes the token in a public gist under the claimed account;
    the platform reads that account's public gists and only records the account as
    verified once it observes the token. Anyone can write a gist, but only the
    account's owner can write one *as that account*, which is what this proves.
    """

    __tablename__ = "agent_github_challenges"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # The claimed GitHub login (user or organisation), lowercased.
    github_login: Mapped[str] = mapped_column(LowercaseString(39), nullable=False)
    token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "github_login", name="agent_github"),
        CheckConstraint(
            "attempt_count >= 0", name="github_attempt_count_non_negative"
        ),
        Index("ix_agent_github_challenges_agent_id", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentGithubChallenge {self.github_login}>"
