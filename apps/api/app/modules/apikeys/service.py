"""API key creation, listing, revocation, and authentication.

The secret is generated here, returned to the caller once, and stored only as a
hash. Authentication hashes the presented key and looks it up by that hash, so the
plaintext never has to exist server-side after creation.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.enums import AccountStatus
from app.modules.apikeys.models import ApiKey
from app.modules.apikeys.scopes import normalize_scopes, unknown_scopes
from app.modules.organizations.models import Organization
from app.modules.users.models import User

# A generous ceiling that still bounds abuse: nobody has a legitimate need for
# hundreds of live keys, and an unbounded count is a way to exhaust storage or
# hide a rogue key in the noise.
MAX_ACTIVE_KEYS_PER_ORG = 25

# last_used_at is written at most this often per key. Every authenticated request
# would otherwise issue a write, turning a read path into a write on every call.
LAST_USED_THROTTLE = timedelta(minutes=1)


async def create_api_key(
    db: AsyncSession,
    *,
    org: Organization,
    creator: User,
    name: str,
    scopes: list[str],
    expires_in_days: int | None,
) -> tuple[ApiKey, str]:
    """Mint a key for an organization. Returns the row and the plaintext token
    (shown once). The key acts as its creator, confined to its granted scopes."""
    unknown = unknown_scopes(scopes)
    if unknown:
        raise ValidationError(
            f"Unknown scope(s): {', '.join(unknown)}.",
            code="unknown_scope",
            details={"unknown": unknown},
        )
    granted = normalize_scopes(scopes)

    active_count = (
        await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.org_id == org.id, ApiKey.revoked_at.is_(None))
        )
    ).scalar_one()
    if active_count >= MAX_ACTIVE_KEYS_PER_ORG:
        raise ConflictError(
            f"This organization already has the maximum of {MAX_ACTIVE_KEYS_PER_ORG} "
            "active API keys. Revoke one before creating another.",
            code="too_many_api_keys",
        )

    token = security.generate_api_key()
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )
    key = ApiKey(
        org_id=org.id,
        created_by_user_id=creator.id,
        name=name,
        # Enough of the key to recognise it, not enough to use it.
        prefix=token[:12],
        token_hash=security.hash_token(token),
        scopes=granted,
        expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key, token


async def list_api_keys(db: AsyncSession, *, org: Organization) -> list[ApiKey]:
    """Every key the organization holds, newest first. Revoked keys are retained
    so the history of what once had access stays visible rather than vanishing."""
    rows = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.org_id == org.id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars()
    return list(rows)


async def revoke_api_key(
    db: AsyncSession, *, org: Organization, key_id: uuid.UUID
) -> ApiKey:
    key = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == org.id)
        )
    ).scalar_one_or_none()
    if key is None:
        raise NotFoundError("No such API key.")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        key.revoked_reason = "revoked_by_owner"
        await db.commit()
        await db.refresh(key)
    return key


async def authenticate(db: AsyncSession, *, token: str) -> tuple[User, ApiKey]:
    """Resolve a plaintext key to the user it acts as, or raise.

    A key belongs to an organization and acts as the member who created it. Rejects
    anything not shaped like a key before touching the database, then loads by hash
    and enforces revocation, expiry, and the acting user's account status, a valid
    key over a suspended account must not grant access. If the creator has been
    removed (created_by_user_id set null), the key no longer resolves to anyone and
    is rejected.
    """
    from app.core.errors import AuthenticationError, PermissionDeniedError

    if not token or not token.startswith(security.API_KEY_PREFIX):
        raise AuthenticationError("Invalid API key.", code="invalid_api_key")

    key = (
        await db.execute(
            select(ApiKey).where(ApiKey.token_hash == security.hash_token(token))
        )
    ).scalar_one_or_none()
    if key is None:
        raise AuthenticationError("Invalid API key.", code="invalid_api_key")
    if key.revoked_at is not None:
        raise AuthenticationError("This API key has been revoked.", code="key_revoked")
    if key.expires_at is not None and key.expires_at <= datetime.now(UTC):
        raise AuthenticationError("This API key has expired.", code="key_expired")

    user = (
        await db.execute(
            select(User).where(User.id == key.created_by_user_id)
        )
        if key.created_by_user_id is not None
        else None
    )
    user = user.scalar_one_or_none() if user is not None else None
    if user is None:
        raise AuthenticationError("Invalid API key.", code="invalid_api_key")
    if user.status in {AccountStatus.SUSPENDED_BY_ADMIN, AccountStatus.DEACTIVATED}:
        raise PermissionDeniedError(
            "This account is not permitted to perform this action.",
            code="account_suspended",
        )

    # The key acts within its organization; if its creator no longer belongs to
    # that org, the key must stop working, otherwise removing a member would leave
    # their programmatic access intact.
    from app.modules.organizations.authz import get_membership

    if await get_membership(db, org_id=key.org_id, user_id=user.id) is None:
        raise AuthenticationError(
            "This API key is no longer active.", code="key_revoked"
        )

    await _touch_last_used(db, key)
    return user, key


async def _touch_last_used(db: AsyncSession, key: ApiKey) -> None:
    """Record use, but at most once per throttle window to avoid a write per call."""
    now = datetime.now(UTC)
    if key.last_used_at is not None and now - key.last_used_at < LAST_USED_THROTTLE:
        return
    key.last_used_at = now
    await db.commit()
