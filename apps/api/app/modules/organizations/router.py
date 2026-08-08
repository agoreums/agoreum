"""Organization and team-management endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.db.enums import OrgRole
from app.modules.organizations import events as org_events
from app.modules.organizations import service
from app.modules.organizations.authz import OrgAction, require_permission
from app.modules.organizations.models import Organization
from app.modules.organizations.schemas import (
    InvitationView,
    MemberAdd,
    MemberRoleUpdate,
    MemberView,
    OrganizationSummary,
    OrgCreate,
    OrgUpdate,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])


async def _load_org(db: DbSession, slug: str) -> Organization:
    org = await service.get_org_by_slug(db, slug=slug)
    if org is None:
        raise NotFoundError("Organization not found.", code="org_not_found")
    return org


@router.get("", response_model=list[OrganizationSummary], summary="Organizations you belong to")
async def my_orgs(user: CurrentUser, db: DbSession) -> list[OrganizationSummary]:
    return await service.list_my_orgs(db, user=user)


@router.post(
    "",
    response_model=OrganizationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team organization",
)
async def create_org(
    payload: OrgCreate, user: CurrentUser, db: DbSession
) -> OrganizationSummary:
    org = await service.create_team_org(db, user=user, slug=payload.slug, name=payload.name)
    return await service.summary_for(db, org=org, role=OrgRole.OWNER)


@router.get("/{slug}", response_model=OrganizationSummary, summary="An organization")
async def get_org(slug: str, user: CurrentUser, db: DbSession) -> OrganizationSummary:
    org = await _load_org(db, slug)
    membership = await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.VIEW
    )
    return await service.summary_for(db, org=org, role=membership.role)


@router.patch("/{slug}", response_model=OrganizationSummary, summary="Rename an organization")
async def update_org(
    slug: str, payload: OrgUpdate, user: CurrentUser, db: DbSession
) -> OrganizationSummary:
    org = await _load_org(db, slug)
    membership = await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    org.name = payload.name.strip()
    await db.flush()
    return await service.summary_for(db, org=org, role=membership.role)


@router.get("/{slug}/members", response_model=list[MemberView], summary="Members")
async def list_members(slug: str, user: CurrentUser, db: DbSession) -> list[MemberView]:
    org = await _load_org(db, slug)
    await require_permission(db, org_id=org.id, user_id=user.id, action=OrgAction.VIEW)
    rows = await service.list_members(db, org=org)
    return [
        MemberView(
            user_id=m.user_id,
            role=m.role,
            username=u.username,
            display_name=u.display_name,
            primary_address=u.primary_address,
            joined_at=m.created_at,
        )
        for m, u in rows
    ]


@router.post(
    "/{slug}/invitations",
    response_model=InvitationView,
    status_code=status.HTTP_201_CREATED,
    summary="Invite somebody to join",
)
async def invite_member(
    slug: str, payload: MemberAdd, user: CurrentUser, db: DbSession
) -> InvitationView:
    """Offer membership. The invitee decides whether to accept.

    This replaced adding a member directly. Membership decides who is notified
    about an organization's orders and whose name is attached to it, so one party
    should not be able to impose it on another.
    """
    org = await _load_org(db, slug)
    await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    invitation, invitee = await service.invite_member(
        db, org=org, actor=user, address=payload.address, role=payload.role
    )
    await org_events.organization_invitation_sent(
        db, org=org, invitation=invitation, invitee=invitee
    )
    return _invitation_view(invitation, org)


@router.get(
    "/{slug}/invitations",
    response_model=list[InvitationView],
    summary="Invitations awaiting an answer",
)
async def list_org_invitations(
    slug: str, user: CurrentUser, db: DbSession
) -> list[InvitationView]:
    org = await _load_org(db, slug)
    await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    return [
        _invitation_view(i, org)
        for i in await service.list_invitations_for_org(db, org=org)
    ]


@router.delete(
    "/{slug}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw an invitation",
)
async def revoke_invitation(
    slug: str, invitation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    org = await _load_org(db, slug)
    await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    await service.revoke_invitation(db, org=org, invitation_id=invitation_id)


@router.patch(
    "/{slug}/members/{user_id}",
    response_model=MemberView,
    summary="Change a member's role",
)
async def update_member(
    slug: str,
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    user: CurrentUser,
    db: DbSession,
) -> MemberView:
    org = await _load_org(db, slug)
    actor = await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    membership = await service.update_member_role(
        db, org=org, actor=actor, target_user_id=user_id, role=payload.role
    )
    target = await service.get_member_user(db, user_id=user_id)
    return MemberView(
        user_id=user_id,
        role=membership.role,
        username=target.username if target else None,
        display_name=target.display_name if target else None,
        primary_address=target.primary_address if target else "",
        joined_at=membership.created_at,
    )


@router.delete(
    "/{slug}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
)
async def remove_member(
    slug: str, user_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    org = await _load_org(db, slug)
    actor = await require_permission(
        db, org_id=org.id, user_id=user.id, action=OrgAction.MANAGE_MEMBERS
    )
    await service.remove_member(db, org=org, actor=actor, target_user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{slug}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave an organization",
)
async def leave_org(slug: str, user: CurrentUser, db: DbSession) -> Response:
    org = await _load_org(db, slug)
    await require_permission(db, org_id=org.id, user_id=user.id, action=OrgAction.VIEW)
    await service.leave_org(db, org=org, user=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/invitations/mine",
    response_model=list[InvitationView],
    summary="Invitations waiting for you",
)
async def my_invitations(user: CurrentUser, db: DbSession) -> list[InvitationView]:
    rows = await service.list_invitations_for_user(db, user=user)
    return [_invitation_view(i, i.organization) for i in rows]


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=OrganizationSummary,
    summary="Accept an invitation",
)
async def accept_invitation(
    invitation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OrganizationSummary:
    membership = await service.accept_invitation(
        db, invitation_id=invitation_id, user=user
    )
    org = await service.get_org_by_id(db, org_id=membership.org_id)
    return await service.summary_for(db, org=org, role=membership.role)


@router.post(
    "/invitations/{invitation_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline an invitation",
)
async def decline_invitation(
    invitation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    await service.decline_invitation(db, invitation_id=invitation_id, user=user)


def _invitation_view(invitation, org) -> InvitationView:
    return InvitationView(
        id=invitation.id,
        org_id=org.id,
        org_slug=org.slug,
        org_name=org.name,
        role=invitation.role,
        invited_user_id=invitation.user_id,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )
