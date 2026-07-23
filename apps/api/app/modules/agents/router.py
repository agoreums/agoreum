"""Agent registration and identity endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.errors import NotFoundError
from app.core.rate_limit import limiter
from app.db.enums import AgentStatus
from app.modules.agents import service
from app.modules.agents.schemas import (
    AgentCreate,
    AgentOwnerView,
    AgentPayoutUpdate,
    AgentPublic,
    AgentUpdate,
    DomainChallengeCreate,
    DomainChallengeResponse,
    validate_slug,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _challenge_response(challenge, *, with_instructions: bool = True):
    payload = DomainChallengeResponse.model_validate(challenge)
    if with_instructions:
        payload.instructions = service.challenge_instructions(challenge)
    return payload


@router.get(
    "/slug-available",
    summary="Check whether an agent name is free",
)
async def slug_available(
    db: DbSession, slug: str = Query(min_length=2, max_length=64)
) -> dict[str, object]:
    """Advisory only. Registration re-checks under the unique index, which is
    the authority — this exists so a form can warn before submission."""
    try:
        normalised = validate_slug(slug)
    except ValueError as exc:
        return {"slug": slug, "available": False, "reason": str(exc)}

    available = await service.is_slug_available(db, normalised)
    return {
        "slug": normalised,
        "available": available,
        "reason": None if available else "That name is already taken.",
    }


@router.get(
    "/mine",
    response_model=list[AgentOwnerView],
    summary="Agents owned by the signed-in user",
)
async def my_agents(user: CurrentUser, db: DbSession) -> list[AgentOwnerView]:
    agents = await service.list_for_owner(db, owner_id=user.id)
    return [AgentOwnerView.model_validate(a) for a in agents]


@router.post(
    "",
    response_model=AgentOwnerView,
    status_code=status.HTTP_201_CREATED,
    summary="Register an agent",
    dependencies=[Depends(limiter("agents:create"))],
)
async def create_agent(
    payload: AgentCreate, user: CurrentUser, db: DbSession
) -> AgentOwnerView:
    agent = await service.create_agent(db, owner=user, payload=payload)
    return AgentOwnerView.model_validate(agent)


@router.get(
    "/{slug}",
    response_model=AgentPublic,
    summary="An agent's public profile",
)
async def get_agent(slug: str, db: DbSession, user: OptionalUser) -> AgentPublic:
    """Drafts and retired agents are visible only to their owner.

    A non-owner gets a 404 rather than a 403, so the existence of an unpublished
    agent is not disclosed.
    """
    agent = await service.require_agent(db, slug)

    hidden = agent.status in {AgentStatus.DRAFT, AgentStatus.RETIRED}
    if hidden and (user is None or agent.owner_id != user.id):
        raise NotFoundError("No agent exists with that name.")

    return AgentPublic.model_validate(agent)


@router.patch(
    "/{slug}", response_model=AgentOwnerView, summary="Update an agent"
)
async def update_agent(
    slug: str, payload: AgentUpdate, user: CurrentUser, db: DbSession
) -> AgentOwnerView:
    agent = await service.require_owned_agent(db, slug, user=user)
    updated = await service.update_agent(db, agent=agent, payload=payload)
    return AgentOwnerView.model_validate(updated)


@router.put(
    "/{slug}/payout-wallet",
    response_model=AgentOwnerView,
    summary="Set where this agent is paid",
)
async def set_payout_wallet(
    slug: str, payload: AgentPayoutUpdate, user: CurrentUser, db: DbSession
) -> AgentOwnerView:
    agent = await service.require_owned_agent(db, slug, user=user)
    updated = await service.set_payout_wallet(
        db, agent=agent, wallet_id=payload.wallet_id, owner=user
    )
    return AgentOwnerView.model_validate(updated)


@router.post(
    "/{slug}/publish",
    response_model=AgentOwnerView,
    summary="List an agent publicly",
)
async def publish_agent(
    slug: str, user: CurrentUser, db: DbSession
) -> AgentOwnerView:
    agent = await service.require_owned_agent(db, slug, user=user)
    return AgentOwnerView.model_validate(
        await service.publish_agent(db, agent=agent)
    )


@router.post(
    "/{slug}/pause",
    response_model=AgentOwnerView,
    summary="Hide an agent from discovery",
)
async def pause_agent(slug: str, user: CurrentUser, db: DbSession) -> AgentOwnerView:
    agent = await service.require_owned_agent(db, slug, user=user)
    return AgentOwnerView.model_validate(await service.pause_agent(db, agent=agent))


@router.post(
    "/{slug}/retire",
    response_model=AgentOwnerView,
    summary="Permanently withdraw an agent",
)
async def retire_agent(slug: str, user: CurrentUser, db: DbSession) -> AgentOwnerView:
    agent = await service.require_owned_agent(db, slug, user=user)
    return AgentOwnerView.model_validate(await service.retire_agent(db, agent=agent))


# --- Domain verification ----------------------------------------------------


@router.post(
    "/{slug}/domain-challenges",
    response_model=DomainChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start proving control of a domain",
)
async def create_domain_challenge(
    slug: str, payload: DomainChallengeCreate, user: CurrentUser, db: DbSession
) -> DomainChallengeResponse:
    agent = await service.require_owned_agent(db, slug, user=user)
    challenge = await service.create_domain_challenge(
        db, agent=agent, domain=payload.domain, method=payload.method
    )
    return _challenge_response(challenge)


@router.post(
    "/{slug}/domain-challenges/{challenge_id}/verify",
    response_model=DomainChallengeResponse,
    summary="Check the published proof",
    dependencies=[Depends(limiter("agents:verify_domain"))],
)
async def verify_domain_challenge(
    slug: str, challenge_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DomainChallengeResponse:
    """Performs a real DNS lookup or HTTPS fetch. Never succeeds without
    observing the token."""
    agent = await service.require_owned_agent(db, slug, user=user)
    challenge = await service.get_challenge(db, agent=agent, challenge_id=challenge_id)
    verified = await service.verify_domain_challenge(
        db, challenge=challenge, agent=agent
    )
    return _challenge_response(verified, with_instructions=False)
