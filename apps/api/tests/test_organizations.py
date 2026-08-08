"""Organization and membership tests.

The permission-matrix tests are pure and run anywhere. The rest need a database
and skip when none is reachable, like the other database-backed suites.
"""
from __future__ import annotations

import secrets

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.errors import ConflictError, PermissionDeniedError
from app.db.enums import OrgKind, OrgRole
from app.modules.organizations import service
from app.modules.organizations.authz import OrgAction, role_can
from app.modules.organizations.models import OrganizationMembership
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


def test_permission_matrix() -> None:
    # Members build; they do not touch money, security, or the team.
    assert role_can(OrgRole.MEMBER, OrgAction.MANAGE_AGENTS)
    assert role_can(OrgRole.MEMBER, OrgAction.ACT_ON_ORDERS)
    assert not role_can(OrgRole.MEMBER, OrgAction.MANAGE_PAYOUT)
    assert not role_can(OrgRole.MEMBER, OrgAction.MANAGE_KEYS)
    assert not role_can(OrgRole.MEMBER, OrgAction.MANAGE_MEMBERS)
    # Admins manage money, keys, and the team, but not ownership.
    assert role_can(OrgRole.ADMIN, OrgAction.MANAGE_PAYOUT)
    assert role_can(OrgRole.ADMIN, OrgAction.MANAGE_KEYS)
    assert role_can(OrgRole.ADMIN, OrgAction.MANAGE_MEMBERS)
    assert not role_can(OrgRole.ADMIN, OrgAction.MANAGE_OWNERS)
    # Owners can do everything.
    assert all(role_can(OrgRole.OWNER, action) for action in OrgAction)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        # Fail fast when nothing is listening. The default waits out a full
        # TCP timeout per test, which turns a skipped suite on a machine with
        # no database into an hour of nothing.
        connect_args={"timeout": 5},
    )
    try:
        async with engine.connect() as probe:
            await probe.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"no database reachable: {type(exc).__name__}")
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def _addr() -> str:
    return "0x" + secrets.token_hex(20)


async def _user(db: AsyncSession) -> User:
    u = User(primary_address=_addr())
    db.add(u)
    await db.flush()
    return u


async def test_personal_org_is_created_once_with_owner(db: AsyncSession) -> None:
    user = await _user(db)
    org = await service.ensure_personal_org(db, user=user)
    assert org.kind == OrgKind.PERSONAL
    again = await service.ensure_personal_org(db, user=user)
    assert again.id == org.id  # idempotent

    orgs = await service.list_my_orgs(db, user=user)
    assert len(orgs) == 1
    assert orgs[0].role == OrgRole.OWNER
    assert orgs[0].member_count == 1


async def _join(db, *, org, actor, invitee, role):
    """Put somebody in an organization the only way that now exists.

    Membership cannot be granted directly any more: it is an offer the invitee
    accepts. These tests are about what happens once somebody is a member, so
    this collapses the two steps rather than repeating them.
    """
    invitation, _ = await service.invite_member(
        db, org=org, actor=actor, address=invitee.primary_address, role=role
    )
    return await service.accept_invitation(
        db, invitation_id=invitation.id, user=invitee
    )


async def test_team_org_and_membership_flow(db: AsyncSession) -> None:
    owner = await _user(db)
    teammate = await _user(db)
    tag = secrets.token_hex(3)

    org = await service.create_team_org(db, user=owner, slug=f"acme-{tag}", name="Acme")
    assert org.kind == OrgKind.TEAM

    membership = await _join(
        db, org=org, actor=owner, invitee=teammate, role=OrgRole.MEMBER
    )
    assert membership.user_id == teammate.id
    assert membership.role == OrgRole.MEMBER

    members = await service.list_members(db, org=org)
    assert {m.role for m, _ in members} == {OrgRole.OWNER, OrgRole.MEMBER}

    # Promote to admin, then confirm the owner is protected.
    owner_membership = await service.get_member_user(db, user_id=owner.id)
    assert owner_membership is not None


async def test_last_owner_cannot_be_removed_or_demoted(db: AsyncSession) -> None:
    owner = await _user(db)
    tag = secrets.token_hex(3)
    org = await service.create_team_org(db, user=owner, slug=f"solo-{tag}", name="Solo")

    actor = await service.get_member_user(db, user_id=owner.id)
    assert actor is not None
    owner_membership = (
        await db.execute(
            sa.select(OrganizationMembership).where(
                OrganizationMembership.org_id == org.id,
                OrganizationMembership.user_id == owner.id,
            )
        )
    ).scalar_one()

    with pytest.raises(ConflictError):
        await service.update_member_role(
            db, org=org, actor=owner_membership, target_user_id=owner.id, role=OrgRole.MEMBER
        )
    with pytest.raises(ConflictError):
        await service.leave_org(db, org=org, user=owner)


async def test_personal_org_rejects_team_changes(db: AsyncSession) -> None:
    user = await _user(db)
    teammate = await _user(db)
    org = await service.ensure_personal_org(db, user=user)
    with pytest.raises(ConflictError):
        await service.invite_member(
            db, org=org, actor=user, address=teammate.primary_address, role=OrgRole.MEMBER
        )


async def test_only_owner_can_grant_ownership(db: AsyncSession) -> None:
    owner = await _user(db)
    admin_user = await _user(db)
    target = await _user(db)
    tag = secrets.token_hex(3)
    org = await service.create_team_org(db, user=owner, slug=f"team-{tag}", name="Team")
    await _join(db, org=org, actor=owner, invitee=admin_user, role=OrgRole.ADMIN)
    await _join(db, org=org, actor=owner, invitee=target, role=OrgRole.MEMBER)

    admin_membership = (
        await db.execute(
            sa.select(OrganizationMembership).where(
                OrganizationMembership.org_id == org.id,
                OrganizationMembership.user_id == admin_user.id,
            )
        )
    ).scalar_one()

    # An admin cannot promote someone to owner.
    with pytest.raises(PermissionDeniedError):
        await service.update_member_role(
            db, org=org, actor=admin_membership, target_user_id=target.id, role=OrgRole.OWNER
        )
