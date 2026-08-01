"""Permission resolution for organizations.

One place decides what a member may do. A member's role in an organization maps to
a set of allowed actions, ordered so a higher role can do everything a lower role
can. Every ownership check in the platform routes through `require_permission`,
which loads the caller's membership and enforces the action.

A caller who is not a member of the org is told the org does not exist (404) rather
than that they lack permission (403), so org membership is not enumerable.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.db.enums import OrgRole
from app.modules.organizations.models import OrganizationMembership


class OrgAction(StrEnum):
    VIEW = "view"
    MANAGE_AGENTS = "manage_agents"  # create/update/publish agents and services
    ACT_ON_ORDERS = "act_on_orders"  # provider actions on received orders
    MANAGE_PAYOUT = "manage_payout"  # set an agent's payout wallet
    MANAGE_KEYS = "manage_keys"  # API keys and webhooks
    MANAGE_MEMBERS = "manage_members"  # invite/remove members, set member/admin
    MANAGE_OWNERS = "manage_owners"  # add/remove owners, delete the org


_RANK: dict[OrgRole, int] = {OrgRole.MEMBER: 0, OrgRole.ADMIN: 1, OrgRole.OWNER: 2}

# The least role that may perform each action.
_MIN_ROLE: dict[OrgAction, OrgRole] = {
    OrgAction.VIEW: OrgRole.MEMBER,
    OrgAction.MANAGE_AGENTS: OrgRole.MEMBER,
    OrgAction.ACT_ON_ORDERS: OrgRole.MEMBER,
    OrgAction.MANAGE_PAYOUT: OrgRole.ADMIN,
    OrgAction.MANAGE_KEYS: OrgRole.ADMIN,
    OrgAction.MANAGE_MEMBERS: OrgRole.ADMIN,
    OrgAction.MANAGE_OWNERS: OrgRole.OWNER,
}


def role_can(role: OrgRole, action: OrgAction) -> bool:
    return _RANK[role] >= _RANK[_MIN_ROLE[action]]


async def get_membership(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMembership | None:
    return (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == org_id,
                OrganizationMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def require_permission(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID, action: OrgAction
) -> OrganizationMembership:
    """Return the caller's membership if it permits the action, else raise.

    Non-members get 404 (the org is not theirs to see); members lacking the role
    get 403.
    """
    membership = await get_membership(db, org_id=org_id, user_id=user_id)
    if membership is None:
        raise NotFoundError("Organization not found.", code="org_not_found")
    if not role_can(membership.role, action):
        raise PermissionDeniedError(
            "Your role in this organization does not permit this action.",
            code="org_permission_denied",
        )
    return membership
