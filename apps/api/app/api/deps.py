"""Shared FastAPI dependencies: authentication, authorisation, and request context.

Authorisation here answers only platform-wide questions ("is this an admin?").
Resource-level questions ("may this user edit this service?") are ownership checks
that belong with the resource, because only that module knows what ownership means.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.enums import AccountStatus, UserRole
from app.db.session import get_db
from app.modules.users.models import User

# auto_error=False so a missing header raises our own error envelope rather than
# FastAPI's, keeping every failure response shaped the same way.
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="SIWE session token")


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the authenticated user, or raise 401.

    The token is verified cryptographically first, then the user is loaded to
    confirm the account still exists and is permitted to act. A valid signature
    over a deleted or suspended account must not grant access.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication is required.")

    claims = decode_access_token(credentials.credentials)

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid authentication token.") from exc

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()

    if user is None:
        raise AuthenticationError("Invalid authentication token.")

    if user.status in {AccountStatus.SUSPENDED_BY_ADMIN, AccountStatus.DEACTIVATED}:
        raise PermissionDeniedError(
            "This account is not permitted to perform this action.",
            code="account_suspended",
        )

    return user


async def get_optional_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Resolve the user if a valid token is present, otherwise None.

    For endpoints that serve everyone but personalise for signed-in users. An
    invalid token yields None rather than an error, so a stale token in a browser
    cannot make public pages fail.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except (AuthenticationError, PermissionDeniedError):
        return None


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Administrator access is required.")
    return user


def client_ip(request: Request) -> str | None:
    """The originating client IP.

    Cloudflare and Nginx sit in front of this service, so the socket peer is a
    proxy. `CF-Connecting-IP` is set by Cloudflare and cannot be spoofed by a
    client through it; `X-Forwarded-For` is only consulted as a fallback and its
    first entry is used.
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()[:45]

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]

    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    ua = request.headers.get("User-Agent")
    return ua[:512] if ua else None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
