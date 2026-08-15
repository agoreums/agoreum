"""Shared FastAPI dependencies: authentication, authorisation, and request context.

Authorisation here answers only platform-wide questions ("is this an admin?").
Resource-level questions ("may this user edit this service?") are ownership checks
that belong with the resource, because only that module knows what ownership means.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import API_KEY_PREFIX, decode_access_token
from app.db.enums import AccountStatus, UserRole
from app.db.session import get_db
from app.modules.apikeys import service as apikey_service
from app.modules.apikeys.models import ApiKey
from app.modules.apikeys.scopes import SCOPES
from app.modules.users.models import Session, User

# auto_error=False so a missing header raises our own error envelope rather than
# FastAPI's, keeping every failure response shaped the same way.
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="SIWE session token")


async def get_current_user(
    request: Request,
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
        session_id = uuid.UUID(claims["sid"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid authentication token.") from exc

    # The access token is joined to its session rather than trusted on its own.
    # A JWT is valid until it expires, so without this check a token stolen and
    # then detected as stolen would keep working for the remainder of its life, 
    # up to fifteen minutes of authenticated access after revocation. On a
    # platform that moves money that window is unacceptable, and the cost is one
    # indexed lookup that replaces the user query we were already doing.
    row = (
        await db.execute(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(
                User.id == user_id,
                Session.id == session_id,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise AuthenticationError(
            "Your session is no longer valid. Please sign in again.",
            code="session_revoked",
        )

    user = row

    if user.status in {AccountStatus.SUSPENDED_BY_ADMIN, AccountStatus.DEACTIVATED}:
        raise PermissionDeniedError(
            "This account is not permitted to perform this action.",
            code="account_suspended",
        )

    # Publish the identity for anything later in the request that wants a fully
    # authorised principal rather than a token subject. Set after the session and
    # account status checks for that reason.
    #
    # This is no longer what makes the rate limiter count by account, and a
    # previous version of this comment claimed it was. Limiters are declared as
    # route-level dependencies, and FastAPI resolves those before the path
    # function's own parameters, so the limiter has already run by the time this
    # line executes. `client_identity` reads the bearer token itself for that
    # reason. Moving this earlier would not help; the ordering is the point.
    request.state.user_id = str(user.id)
    # The session this token belongs to, so a handler can act on the caller's own
    # session without being handed the refresh token. Logout uses it to end the
    # current session when the caller only has an access token.
    request.state.session_id = str(session_id)

    return user


async def get_optional_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Resolve the user if a valid token is present, otherwise None.

    For endpoints that serve everyone but personalise for signed-in users. An
    invalid token yields None rather than an error, so a stale token in a browser
    cannot make public pages fail.

    `request` is threaded through so a signed-in caller on a public endpoint is
    still rate limited by account rather than by address, exactly as on a private
    one. Anonymous callers set nothing and keep the IP bucket.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_current_user(request, credentials, db)
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


# --- Programmatic access: API keys ------------------------------------------
#
# The public API is reachable two ways: by a browser session (the site itself) or
# by an API key (an SDK or another agent). A *principal* unifies them so an endpoint
# is written once and works for both. A session carries the user's full authority;
# an API key carries only its granted scopes.

# The full set of scope strings, granted implicitly to a session principal so that
# a browser can do anything its user could.
ALL_SCOPES: frozenset[str] = frozenset(SCOPES)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="API key")


@dataclass(frozen=True)
class Principal:
    """Who is making a programmatic request, and what they are allowed to do."""

    user: User
    scopes: frozenset[str]
    # The key used, when authenticated by API key; None for a browser session.
    api_key: ApiKey | None

    @property
    def via_api_key(self) -> bool:
        return self.api_key is not None

    @property
    def org_scope(self) -> uuid.UUID | None:
        """The one organization this caller may act in, or None for no limit.

        A key is minted inside an organization, is listed under it, and is
        chosen per organization in the interface, so its holder reasonably
        believes it cannot reach anywhere else. Until this existed that belief
        was wrong: the key was resolved to its creator and then carried that
        person's full authority across *every* organization they belong to, so a
        key minted for a personal side project could register agents in an
        employer's organization. Verified against the running app before it was
        fixed, not inferred.

        The organization was checked exactly once, at authentication, to confirm
        the creator is still a member. That is a different question from which
        organization the key may act in, and answering the first was being
        mistaken for answering the second.

        A browser session returns None on purpose. A signed-in person switches
        organizations in the interface and is meant to act in all of theirs;
        it is the credential that lives in a config file somewhere that needs
        containing.
        """
        return self.api_key.org_id if self.api_key is not None else None

    def has_scopes(self, required: frozenset[str]) -> bool:
        return required <= self.scopes


async def get_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    api_key_value: Annotated[str | None, Security(api_key_header)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """Resolve a principal from either an API key or a browser session.

    An API key may arrive as `X-API-Key: ak_...` or as `Authorization: Bearer ak_...`;
    both are supported because different HTTP clients favour different conventions.
    A bearer credential that is not shaped like a key is treated as a session JWT.
    """
    bearer = credentials.credentials if credentials else None

    key_token = api_key_value or (
        bearer if bearer and bearer.startswith(API_KEY_PREFIX) else None
    )
    if key_token:
        user, key = await apikey_service.authenticate(db, token=key_token)
        # Published for anything later in the request that wants the account:
        # logging, auditing, error context.
        #
        # This does NOT decide the rate limit bucket, and a previous version of
        # this comment claimed it did. Limiters are route-level dependencies and
        # FastAPI resolves those before a path function's own parameters, so the
        # limiter has already run by the time this line executes. The claim was
        # false for the same reason `client_identity` documents at length, and
        # key traffic was counted against its IP address for as long as it stood.
        # The limiter now recognises a key from the request headers directly.
        request.state.user_id = str(user.id)
        return Principal(user=user, scopes=frozenset(key.scopes), api_key=key)

    if bearer:
        user = await get_current_user(request, credentials, db)
        # A signed-in human acts with full authority; scopes only ever narrow a key.
        return Principal(user=user, scopes=ALL_SCOPES, api_key=None)

    raise AuthenticationError(
        "Provide an API key (X-API-Key) or sign in.", code="unauthenticated"
    )


def require_scopes(*required: str):
    """Build a dependency that authenticates a principal and enforces scopes.

    Session principals always pass (they hold every scope); API-key principals must
    carry all of the listed scopes or the request is refused with 403.
    """
    needed = frozenset(required)
    unknown = needed - ALL_SCOPES
    if unknown:  # a wiring mistake, caught at import rather than at request time
        raise ValueError(f"require_scopes referenced unknown scope(s): {sorted(unknown)}")

    async def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if not principal.has_scopes(needed):
            missing = sorted(needed - principal.scopes)
            raise PermissionDeniedError(
                f"This API key is missing the required scope(s): {', '.join(missing)}.",
                code="insufficient_scope",
                details={"missing": missing},
            )
        return principal

    return dependency


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]

# Ready-made scope dependencies for endpoints exposed to programmatic callers. A
# browser session satisfies any of these (it holds every scope); an API key must
# carry the named scope. Endpoints use these instead of CurrentUser to become
# reachable by API key without any change to how the web app calls them.
AgentsRead = Annotated[Principal, Depends(require_scopes("agents:read"))]
OrdersRead = Annotated[Principal, Depends(require_scopes("orders:read"))]

# The write side. These were declared in the scope catalogue, offered when
# minting a key, and enforced by nothing, because every write endpoint took
# CurrentUser, which is session only and refuses a key outright. A key holding
# every scope the product offers still got 401 on every write, so the SDK could
# read and never act, which is the opposite of what the scope descriptions
# promise anybody reading them.
#
# Each is granted only by naming it at mint time. Nothing here is implied by a
# read scope, and nothing is bundled: a key that can read orders still cannot
# place one unless `orders:write` was chosen deliberately.
AgentsWrite = Annotated[Principal, Depends(require_scopes("agents:write"))]
ServicesWrite = Annotated[Principal, Depends(require_scopes("services:write"))]
OrdersWrite = Annotated[Principal, Depends(require_scopes("orders:write"))]
