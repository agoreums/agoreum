"""Agent registration, identity, and lifecycle."""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.db.enums import (
    AccountStatus,
    AgentStatus,
    AgentVerificationTier,
    WalletVerificationStatus,
)
from app.modules.agents.models import (
    Agent,
    AgentDomainChallenge,
    AgentGithubChallenge,
)
from app.modules.agents.schemas import AgentCreate, AgentUpdate
from app.modules.users.models import User, Wallet

logger = get_logger(__name__)

# How many agents one account may register. A limit exists so a single actor
# cannot flood discovery with near-duplicate listings; it is generous enough that
# a legitimate operator running a fleet is not obstructed.
MAX_AGENTS_PER_USER = 25

DOMAIN_CHALLENGE_TTL = timedelta(days=7)
DNS_TXT_PREFIX = "agoreum-verification"

GITHUB_CHALLENGE_TTL = timedelta(days=7)
GITHUB_TOKEN_PREFIX = "agoreum-verification"  # noqa: S105 - a public label, not a secret
# GitHub logins: 1-39 chars, alphanumeric or single hyphens, not starting/ending
# with a hyphen. Validated before it is ever placed in a request path.
_GITHUB_LOGIN_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")


# --- Reads ------------------------------------------------------------------


async def get_by_slug(db: AsyncSession, slug: str) -> Agent | None:
    return (
        await db.execute(select(Agent).where(Agent.slug == slug.lower()))
    ).scalar_one_or_none()


async def get_by_id(db: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    return (
        await db.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()


async def require_agent(db: AsyncSession, slug: str) -> Agent:
    agent = await get_by_slug(db, slug)
    if agent is None:
        raise NotFoundError("No agent exists with that name.")
    return agent


async def require_owned_agent(
    db: AsyncSession, slug: str, *, user: User
) -> Agent:
    """Load an agent the caller is allowed to modify.

    A non-owner gets the same 404 a stranger would, rather than a 403. Telling
    someone "this exists but is not yours" leaks the existence of private drafts.
    """
    agent = await get_by_slug(db, slug)
    if agent is None or agent.owner_id != user.id:
        raise NotFoundError("No agent exists with that name.")
    return agent


async def list_for_owner(db: AsyncSession, *, owner_id: uuid.UUID) -> list[Agent]:
    result = await db.execute(
        select(Agent)
        .where(Agent.owner_id == owner_id)
        .order_by(Agent.created_at.desc())
    )
    return list(result.scalars().all())


async def is_slug_available(db: AsyncSession, slug: str) -> bool:
    existing = (
        await db.execute(select(Agent.id).where(Agent.slug == slug.lower()))
    ).first()
    return existing is None


# --- Writes -----------------------------------------------------------------


async def create_agent(
    db: AsyncSession, *, owner: User, payload: AgentCreate
) -> Agent:
    """Register a new agent, owned by the calling user.

    Agents start as drafts. Publishing is a separate action that checks the
    agent is actually ready — an unpublished agent cannot be ordered from.
    """
    if owner.status != AccountStatus.ACTIVE:
        raise PermissionDeniedError(
            "Your account cannot register agents in its current state."
        )

    count = (
        await db.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.owner_id == owner.id,
                Agent.status != AgentStatus.RETIRED,
            )
        )
    ).scalar_one()

    if count >= MAX_AGENTS_PER_USER:
        raise ConflictError(
            f"You have reached the limit of {MAX_AGENTS_PER_USER} agents.",
            code="agent_limit_reached",
        )

    agent = Agent(
        owner_id=owner.id,
        slug=payload.slug,
        name=payload.name.strip(),
        tagline=payload.tagline,
        description=payload.description,
        website_url=payload.website_url,
        avatar_url=payload.avatar_url,
        capabilities=payload.capabilities,
        api_endpoint=payload.api_endpoint,
        status=AgentStatus.DRAFT,
    )
    db.add(agent)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # The unique index is the authority. Checking availability first would
        # still leave a race between the check and the insert.
        raise ConflictError(
            "That agent name is already taken.", code="slug_taken"
        ) from exc

    logger.info(
        "agent_created", extra={"agent_id": str(agent.id), "owner": str(owner.id)}
    )
    return agent


async def update_agent(
    db: AsyncSession, *, agent: Agent, payload: AgentUpdate
) -> Agent:
    """Apply a partial update. Only fields explicitly supplied are changed."""
    changes = payload.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(agent, field, value)

    # Changing the site invalidates any domain proof tied to the old one.
    if "website_url" in changes and agent.verified_domain:
        new_host = _host_of(changes["website_url"])
        if new_host != agent.verified_domain:
            logger.info(
                "agent_domain_proof_invalidated", extra={"agent_id": str(agent.id)}
            )
            agent.verified_domain = None
            agent.domain_verified_at = None
            agent.verification_tier = AgentVerificationTier.UNVERIFIED

    await db.flush()
    # Reload server-generated columns (updated_at) so serialisation does not
    # trigger lazy IO outside the async context.
    await db.refresh(agent)
    return agent


async def set_payout_wallet(
    db: AsyncSession, *, agent: Agent, wallet_id: uuid.UUID, owner: User
) -> Agent:
    """Point an agent's earnings at one of the owner's verified wallets."""
    wallet = (
        await db.execute(
            select(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == owner.id)
        )
    ).scalar_one_or_none()

    if wallet is None:
        raise NotFoundError("No such wallet on this account.")

    if wallet.verification_status != WalletVerificationStatus.VERIFIED:
        # Enforced by a CHECK constraint too; rejected here so the caller gets a
        # useful message instead of a database error.
        raise ConflictError(
            "That wallet has not been verified. Sign in with it first to prove "
            "you control it.",
            code="wallet_unverified",
        )

    agent.payout_wallet_id = wallet.id
    agent.payout_address = wallet.address
    await db.flush()
    await db.refresh(agent)

    logger.info(
        "agent_payout_wallet_set", extra={"agent_id": str(agent.id)}
    )
    return agent


async def publish_agent(db: AsyncSession, *, agent: Agent) -> Agent:
    """Make an agent publicly listed.

    Publishing is gated on the agent actually being able to trade. An agent
    without a proven payout address cannot be paid, so listing it would be
    advertising something that cannot complete.
    """
    if agent.status == AgentStatus.ACTIVE:
        return agent

    if agent.status == AgentStatus.SUSPENDED:
        raise PermissionDeniedError(
            "This agent is suspended and cannot be published.",
            code="agent_suspended",
        )

    if agent.payout_wallet_id is None:
        raise ConflictError(
            "Set a verified payout wallet before publishing, otherwise this "
            "agent cannot be paid.",
            code="payout_wallet_required",
        )

    agent.status = AgentStatus.ACTIVE
    agent.published_at = agent.published_at or datetime.now(UTC)
    await db.flush()
    await db.refresh(agent)

    logger.info("agent_published", extra={"agent_id": str(agent.id)})
    return agent


async def pause_agent(db: AsyncSession, *, agent: Agent) -> Agent:
    """Hide an agent from discovery without ending work already in progress."""
    if agent.status == AgentStatus.SUSPENDED:
        raise PermissionDeniedError("This agent is suspended.")
    agent.status = AgentStatus.PAUSED
    await db.flush()
    await db.refresh(agent)
    return agent


async def retire_agent(db: AsyncSession, *, agent: Agent) -> Agent:
    """Permanently withdraw an agent.

    The record is kept rather than deleted: orders, reviews, and on-chain
    settlement reference it, and that history must remain readable.
    """
    agent.status = AgentStatus.RETIRED
    await db.flush()
    await db.refresh(agent)
    logger.info("agent_retired", extra={"agent_id": str(agent.id)})
    return agent


# --- Domain verification ----------------------------------------------------


async def create_domain_challenge(
    db: AsyncSession, *, agent: Agent, domain: str, method: str
) -> AgentDomainChallenge:
    """Issue a proof-of-control challenge for a domain."""
    existing = (
        await db.execute(
            select(AgentDomainChallenge).where(
                AgentDomainChallenge.agent_id == agent.id,
                AgentDomainChallenge.domain == domain,
            )
        )
    ).scalar_one_or_none()

    token = f"{DNS_TXT_PREFIX}={secrets.token_urlsafe(24)}"
    expires_at = datetime.now(UTC) + DOMAIN_CHALLENGE_TTL

    if existing is not None:
        # Reissue rather than refuse: the operator may have lost the token, and
        # a fresh one is strictly safer than reusing the old.
        existing.token = token
        existing.method = method
        existing.expires_at = expires_at
        existing.verified_at = None
        existing.attempt_count = 0
        existing.last_error = None
        await db.flush()
        return existing

    challenge = AgentDomainChallenge(
        agent_id=agent.id,
        domain=domain,
        token=token,
        method=method,
        expires_at=expires_at,
    )
    db.add(challenge)
    await db.flush()
    return challenge


def challenge_instructions(challenge: AgentDomainChallenge) -> str:
    if challenge.method == "dns_txt":
        return (
            f"Create a DNS TXT record on {challenge.domain} with the value:\n"
            f"{challenge.token}\n"
            "DNS changes can take a few minutes to propagate."
        )
    return (
        f"Serve the following text at "
        f"https://{challenge.domain}/.well-known/agoreum-verification:\n"
        f"{challenge.token}"
    )


async def verify_domain_challenge(
    db: AsyncSession, *, challenge: AgentDomainChallenge, agent: Agent
) -> AgentDomainChallenge:
    """Check the published proof and, if valid, record the domain as verified.

    The check is a real lookup against real DNS or a real HTTPS fetch. A failure
    is recorded on the challenge so the operator can see why it did not work.
    """
    from app.modules.agents import domain_check

    challenge.attempt_count += 1
    challenge.last_attempt_at = datetime.now(UTC)

    if challenge.expires_at <= datetime.now(UTC):
        challenge.last_error = "This challenge has expired. Request a new one."
        await db.flush()
        raise ConflictError(challenge.last_error, code="challenge_expired")

    if challenge.method == "dns_txt":
        found, error = await domain_check.check_dns_txt(
            challenge.domain, challenge.token
        )
    else:
        found, error = await domain_check.check_well_known(
            challenge.domain, challenge.token
        )

    if not found:
        challenge.last_error = error or "The verification token was not found."
        await db.flush()
        logger.info(
            "domain_verification_failed",
            extra={"agent_id": str(agent.id), "reason": challenge.last_error},
        )
        raise ConflictError(challenge.last_error, code="verification_failed")

    now = datetime.now(UTC)
    challenge.verified_at = now
    challenge.last_error = None

    agent.verified_domain = challenge.domain
    agent.domain_verified_at = now
    # Only ever raises to DOMAIN_VERIFIED. Organisation verification requires a
    # human reviewer and is never granted automatically.
    if agent.verification_tier == AgentVerificationTier.UNVERIFIED:
        agent.verification_tier = AgentVerificationTier.DOMAIN_VERIFIED

    await db.flush()
    logger.info(
        "domain_verified",
        extra={"agent_id": str(agent.id), "domain": challenge.domain},
    )
    return challenge


async def get_challenge(
    db: AsyncSession, *, agent: Agent, challenge_id: uuid.UUID
) -> AgentDomainChallenge:
    challenge = (
        await db.execute(
            select(AgentDomainChallenge).where(
                AgentDomainChallenge.id == challenge_id,
                AgentDomainChallenge.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise NotFoundError("No such verification challenge.")
    return challenge


# --- GitHub verification ----------------------------------------------------


def _normalize_github_login(login: str) -> str:
    """Accept a username, @handle, or profile URL; return the bare login or raise."""
    login = login.strip().lstrip("@")
    prefix = "https://github.com/"
    if login.lower().startswith(prefix):
        login = login[len(prefix):]
    login = login.strip("/").split("/")[0]
    if not _GITHUB_LOGIN_RE.match(login):
        raise ValidationError(
            "That does not look like a GitHub username or organisation.",
            code="invalid_github_login",
        )
    return login.lower()


async def create_github_challenge(
    db: AsyncSession, *, agent: Agent, github_login: str
) -> AgentGithubChallenge:
    """Issue a proof-of-control challenge for a GitHub account or organisation."""
    login = _normalize_github_login(github_login)
    existing = (
        await db.execute(
            select(AgentGithubChallenge).where(
                AgentGithubChallenge.agent_id == agent.id,
                AgentGithubChallenge.github_login == login,
            )
        )
    ).scalar_one_or_none()

    token = f"{GITHUB_TOKEN_PREFIX}={secrets.token_urlsafe(24)}"
    expires_at = datetime.now(UTC) + GITHUB_CHALLENGE_TTL

    if existing is not None:
        # Reissue rather than refuse; a fresh token is strictly safer than reuse.
        existing.token = token
        existing.expires_at = expires_at
        existing.verified_at = None
        existing.attempt_count = 0
        existing.last_error = None
        await db.flush()
        return existing

    challenge = AgentGithubChallenge(
        agent_id=agent.id,
        github_login=login,
        token=token,
        expires_at=expires_at,
    )
    db.add(challenge)
    await db.flush()
    return challenge


def github_challenge_instructions(challenge: AgentGithubChallenge) -> str:
    return (
        f"Signed in as {challenge.github_login} on GitHub, create a public gist with "
        f"this exact text as its description:\n{challenge.token}"
    )


async def get_github_challenge(
    db: AsyncSession, *, agent: Agent, challenge_id: uuid.UUID
) -> AgentGithubChallenge:
    challenge = (
        await db.execute(
            select(AgentGithubChallenge).where(
                AgentGithubChallenge.id == challenge_id,
                AgentGithubChallenge.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise NotFoundError("No such verification challenge.")
    return challenge


async def verify_github_challenge(
    db: AsyncSession, *, challenge: AgentGithubChallenge, agent: Agent
) -> AgentGithubChallenge:
    """Check the published gist and, if valid, record the account as verified.

    The check is a real read of the claimed account's public gists. It never
    succeeds without observing the token.
    """
    from app.modules.agents import github_check

    challenge.attempt_count += 1
    challenge.last_attempt_at = datetime.now(UTC)

    if challenge.expires_at <= datetime.now(UTC):
        challenge.last_error = "This challenge has expired. Request a new one."
        await db.flush()
        raise ConflictError(challenge.last_error, code="challenge_expired")

    found, error = await github_check.check_gist(
        challenge.github_login, challenge.token
    )
    if not found:
        challenge.last_error = error or "The verification token was not found."
        await db.flush()
        logger.info(
            "github_verification_failed",
            extra={"agent_id": str(agent.id), "reason": challenge.last_error},
        )
        raise ConflictError(challenge.last_error, code="verification_failed")

    now = datetime.now(UTC)
    challenge.verified_at = now
    challenge.last_error = None
    agent.verified_github = challenge.github_login
    agent.github_verified_at = now
    await db.flush()
    logger.info(
        "github_verified",
        extra={"agent_id": str(agent.id), "github": challenge.github_login},
    )
    return challenge


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None
