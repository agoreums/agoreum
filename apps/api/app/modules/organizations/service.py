"""Organization and membership operations."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.db.enums import OrgKind, OrgRole
from app.modules.organizations import authz
from app.modules.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.modules.organizations.schemas import OrganizationSummary
from app.modules.users.models import User

logger = logging.getLogger(__name__)

MAX_TEAM_ORGS_PER_USER = 20


def _personal_slug(user_id: uuid.UUID) -> str:
    return "u-" + user_id.hex


async def ensure_personal_org(db: AsyncSession, *, user: User) -> Organization:
    """Return the user's personal org, creating it if missing.

    Called on sign-in so every user always has a namespace of their own. Idempotent.
    """
    slug = _personal_slug(user.id)
    existing = (
        await db.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    org = Organization(
        slug=slug,
        name=user.display_name or user.username or "Personal",
        kind=OrgKind.PERSONAL,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMembership(org_id=org.id, user_id=user.id, role=OrgRole.OWNER))
    await db.flush()
    logger.info("personal_org_created", extra={"user_id": str(user.id), "org_id": str(org.id)})
    return org


async def _member_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(OrganizationMembership).where(
                OrganizationMembership.org_id == org_id
            )
        )
    ).scalar_one()


async def _owner_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.org_id == org_id,
                OrganizationMembership.role == OrgRole.OWNER,
            )
        )
    ).scalar_one()


async def list_my_orgs(db: AsyncSession, *, user: User) -> list[OrganizationSummary]:
    rows = (
        await db.execute(
            select(Organization, OrganizationMembership.role)
            .join(OrganizationMembership, OrganizationMembership.org_id == Organization.id)
            .where(OrganizationMembership.user_id == user.id)
            .order_by(Organization.kind, Organization.name)
        )
    ).all()
    summaries: list[OrganizationSummary] = []
    for org, role in rows:
        summaries.append(
            OrganizationSummary(
                id=org.id,
                slug=org.slug,
                name=org.name,
                kind=org.kind,
                role=role,
                member_count=await _member_count(db, org.id),
            )
        )
    return summaries


async def get_org_by_id(db: AsyncSession, *, org_id: uuid.UUID) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFoundError("No such organization.")
    return org


async def get_org_by_slug(db: AsyncSession, *, slug: str) -> Organization | None:
    return (
        await db.execute(select(Organization).where(Organization.slug == slug.lower()))
    ).scalar_one_or_none()


async def resolve_org_for_action(
    db: AsyncSession,
    *,
    user: User,
    slug: str | None,
    action: authz.OrgAction,
) -> Organization:
    """Resolve which org a request acts under, enforcing the caller's permission.

    With no slug the caller acts under their personal org, which they solely own,
    so the action is always permitted there. With a slug the org must exist and the
    caller must hold a role that permits the action; a non-member gets a 404 so org
    membership stays unenumerable.
    """
    if slug is None:
        return await ensure_personal_org(db, user=user)
    org = await get_org_by_slug(db, slug=slug)
    if org is None:
        raise NotFoundError("Organization not found.", code="org_not_found")
    await authz.require_permission(db, org_id=org.id, user_id=user.id, action=action)
    return org


async def create_team_org(
    db: AsyncSession, *, user: User, slug: str, name: str
) -> Organization:
    count = (
        await db.execute(
            select(func.count())
            .select_from(OrganizationMembership)
            .join(Organization, Organization.id == OrganizationMembership.org_id)
            .where(
                OrganizationMembership.user_id == user.id,
                Organization.kind == OrgKind.TEAM,
            )
        )
    ).scalar_one()
    if count >= MAX_TEAM_ORGS_PER_USER:
        raise ConflictError(
            f"You have reached the limit of {MAX_TEAM_ORGS_PER_USER} organizations.",
            code="org_limit_reached",
        )

    org = Organization(slug=slug, name=name.strip(), kind=OrgKind.TEAM)
    db.add(org)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("That organization name is taken.", code="slug_taken") from exc

    db.add(OrganizationMembership(org_id=org.id, user_id=user.id, role=OrgRole.OWNER))
    await db.flush()
    logger.info("team_org_created", extra={"org_id": str(org.id), "owner": str(user.id)})
    return org


async def list_members(db: AsyncSession, *, org: Organization) -> list[tuple[OrganizationMembership, User]]:
    return list(
        (
            await db.execute(
                select(OrganizationMembership, User)
                .join(User, User.id == OrganizationMembership.user_id)
                .where(OrganizationMembership.org_id == org.id)
                .order_by(OrganizationMembership.role.desc(), OrganizationMembership.created_at)
            )
        ).all()
    )


def _reject_personal(org: Organization) -> None:
    if org.kind == OrgKind.PERSONAL:
        raise ConflictError(
            "A personal organization cannot have its team changed.",
            code="personal_org_immutable",
        )


async def _membership_or_404(
    db: AsyncSession, *, org: Organization, user_id: uuid.UUID
) -> OrganizationMembership:
    membership = await authz.get_membership(db, org_id=org.id, user_id=user_id)
    if membership is None:
        raise NotFoundError("Not a member of this organization.", code="member_not_found")
    return membership


async def update_member_role(
    db: AsyncSession,
    *,
    org: Organization,
    actor: OrganizationMembership,
    target_user_id: uuid.UUID,
    role: OrgRole,
) -> OrganizationMembership:
    _reject_personal(org)
    target = await _membership_or_404(db, org=org, user_id=target_user_id)

    # Granting or removing ownership is an owner-only action.
    if (role == OrgRole.OWNER or target.role == OrgRole.OWNER) and actor.role != OrgRole.OWNER:
        raise PermissionDeniedError(
            "Only an owner can change ownership.", code="org_permission_denied"
        )
    # Never leave an org without an owner.
    if target.role == OrgRole.OWNER and role != OrgRole.OWNER and await _owner_count(db, org.id) <= 1:
        raise ConflictError(
            "An organization must keep at least one owner.", code="last_owner"
        )

    target.role = role
    await db.flush()
    return target


async def remove_member(
    db: AsyncSession, *, org: Organization, actor: OrganizationMembership, target_user_id: uuid.UUID
) -> None:
    _reject_personal(org)
    target = await _membership_or_404(db, org=org, user_id=target_user_id)
    if target.role == OrgRole.OWNER and actor.role != OrgRole.OWNER:
        raise PermissionDeniedError("Only an owner can remove an owner.", code="org_permission_denied")
    if target.role == OrgRole.OWNER and await _owner_count(db, org.id) <= 1:
        raise ConflictError("An organization must keep at least one owner.", code="last_owner")
    await db.delete(target)
    await db.flush()


async def leave_org(db: AsyncSession, *, org: Organization, user: User) -> None:
    _reject_personal(org)
    membership = await _membership_or_404(db, org=org, user_id=user.id)
    if membership.role == OrgRole.OWNER and await _owner_count(db, org.id) <= 1:
        raise ConflictError(
            "Transfer ownership before leaving; an organization must keep an owner.",
            code="last_owner",
        )
    await db.delete(membership)
    await db.flush()


async def get_member_user(db: AsyncSession, *, user_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def summary_for(
    db: AsyncSession, *, org: Organization, role: OrgRole
) -> OrganizationSummary:
    return OrganizationSummary(
        id=org.id,
        slug=org.slug,
        name=org.name,
        kind=org.kind,
        role=role,
        member_count=await _member_count(db, org.id),
    )


# An offer that is never answered should not sit against an account forever.
INVITATION_TTL = timedelta(days=14)


async def invite_member(
    db: AsyncSession, *, org: Organization, actor: User, address: str, role: OrgRole
) -> tuple[OrganizationInvitation, User]:
    """Offer membership. The invitee decides.

    Replaces adding somebody directly. Membership decides who is notified about
    an organization's orders and whose name is attached to it, so it is not
    something one party should be able to impose on another.
    """
    _reject_personal(org)
    user = (
        await db.execute(select(User).where(User.primary_address == address))
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            "No account for that address. Ask them to sign in once first.",
            code="user_not_found",
        )
    if await authz.get_membership(db, org_id=org.id, user_id=user.id) is not None:
        raise ConflictError("Already a member.", code="already_member")

    pending = (
        await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.org_id == org.id,
                OrganizationInvitation.user_id == user.id,
                OrganizationInvitation.responded_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise ConflictError("Already invited.", code="already_invited")

    invitation = OrganizationInvitation(
        org_id=org.id,
        user_id=user.id,
        invited_by_id=actor.id,
        role=role,
        expires_at=datetime.now(UTC) + INVITATION_TTL,
    )
    db.add(invitation)
    await db.flush()
    return invitation, user


async def list_invitations_for_org(
    db: AsyncSession, *, org: Organization
) -> list[OrganizationInvitation]:
    rows = await db.execute(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.org_id == org.id,
            OrganizationInvitation.responded_at.is_(None),
        )
        .order_by(OrganizationInvitation.created_at.desc())
    )
    return list(rows.scalars().all())


async def list_invitations_for_user(
    db: AsyncSession, *, user: User
) -> list[OrganizationInvitation]:
    """Live invitations awaiting this person's answer.

    Expired ones are filtered rather than shown greyed out, because an offer that
    can no longer be accepted is not a decision the person still has to make.
    """
    rows = await db.execute(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.user_id == user.id,
            OrganizationInvitation.responded_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(UTC),
        )
        .order_by(OrganizationInvitation.created_at.desc())
    )
    return list(rows.scalars().all())


async def _claim_invitation(
    db: AsyncSession, *, invitation_id: uuid.UUID, user: User, accepted: bool
) -> OrganizationInvitation:
    """Resolve an invitation exactly once.

    Written as a conditional update rather than read-then-write so two clicks,
    or a click and a retry, cannot both succeed. The same shape as consuming a
    verification token.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.user_id == user.id,
            OrganizationInvitation.responded_at.is_(None),
            OrganizationInvitation.expires_at > now,
        )
        .values(responded_at=now, accepted=accepted)
        .returning(OrganizationInvitation)
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise NotFoundError(
            "That invitation is no longer open.", code="invitation_not_open"
        )
    return invitation


async def accept_invitation(
    db: AsyncSession, *, invitation_id: uuid.UUID, user: User
) -> OrganizationMembership:
    invitation = await _claim_invitation(
        db, invitation_id=invitation_id, user=user, accepted=True
    )
    existing = await authz.get_membership(
        db, org_id=invitation.org_id, user_id=user.id
    )
    if existing is not None:
        return existing
    membership = OrganizationMembership(
        org_id=invitation.org_id, user_id=user.id, role=invitation.role
    )
    db.add(membership)
    await db.flush()
    return membership


async def decline_invitation(
    db: AsyncSession, *, invitation_id: uuid.UUID, user: User
) -> None:
    await _claim_invitation(
        db, invitation_id=invitation_id, user=user, accepted=False
    )


async def revoke_invitation(
    db: AsyncSession, *, org: Organization, invitation_id: uuid.UUID
) -> None:
    """Withdraw an offer that has not been answered."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.org_id == org.id,
            OrganizationInvitation.responded_at.is_(None),
        )
        .values(responded_at=now, accepted=False)
        .returning(OrganizationInvitation.id)
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundError(
            "That invitation is no longer open.", code="invitation_not_open"
        )
