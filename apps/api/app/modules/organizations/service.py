"""Organization and membership operations."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.db.enums import OrgKind, OrgRole
from app.modules.organizations import authz
from app.modules.organizations.models import Organization, OrganizationMembership
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


async def get_org_by_slug(db: AsyncSession, *, slug: str) -> Organization | None:
    return (
        await db.execute(select(Organization).where(Organization.slug == slug.lower()))
    ).scalar_one_or_none()


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


async def add_member(
    db: AsyncSession, *, org: Organization, address: str, role: OrgRole
) -> tuple[OrganizationMembership, User]:
    _reject_personal(org)
    user = (
        await db.execute(select(User).where(User.primary_address == address))
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            "No account for that address. Ask them to sign in once first.",
            code="user_not_found",
        )
    existing = await authz.get_membership(db, org_id=org.id, user_id=user.id)
    if existing is not None:
        raise ConflictError("Already a member.", code="already_member")

    membership = OrganizationMembership(org_id=org.id, user_id=user.id, role=role)
    db.add(membership)
    await db.flush()
    return membership, user


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
