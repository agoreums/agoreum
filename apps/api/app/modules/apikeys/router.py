"""API key management endpoints.

These are authenticated by the browser session (a signed-in user managing their own
keys), not by an API key. The keys they mint are what authenticate the programmatic
API; see `app.api.deps.ApiKeyPrincipal`.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.modules.apikeys import service
from app.modules.apikeys.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyList,
    ApiKeyPublic,
    ScopeCatalog,
)
from app.modules.organizations import service as org_service
from app.modules.organizations.authz import OrgAction

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

# API keys are managed within an organization. The `org` query parameter selects
# which one; omitted, it is the caller's personal organization, so a solo creator
# manages keys exactly as before. Minting and revoking require the keys role.
OrgSlug = Annotated[str | None, Query(alias="org", max_length=64)]


@router.get("/scopes", response_model=ScopeCatalog, summary="Available API key scopes")
async def scopes() -> ScopeCatalog:
    """The scopes a key may be granted. Public so the docs and the key-creation UI
    can render the catalogue without a session."""
    return ScopeCatalog()


@router.get("", response_model=ApiKeyList, summary="An organization's API keys")
async def list_keys(
    user: CurrentUser, db: DbSession, org: OrgSlug = None
) -> ApiKeyList:
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    keys = await service.list_api_keys(db, org=organization)
    return ApiKeyList(
        items=[ApiKeyPublic.model_validate(k) for k in keys], total=len(keys)
    )


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
)
async def create_key(
    payload: ApiKeyCreate, user: CurrentUser, db: DbSession, org: OrgSlug = None
) -> ApiKeyCreated:
    """Mint a key. The plaintext token is in the response and is shown only here,
    it cannot be retrieved again, only replaced."""
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    key, token = await service.create_api_key(
        db,
        org=organization,
        creator=user,
        name=payload.name,
        scopes=payload.scopes,
        expires_in_days=payload.expires_in_days,
    )
    # The ORM row has no `token` attribute, so validate it to the public shape
    # first, then attach the plaintext secret, the one and only time it is shown.
    public = ApiKeyPublic.model_validate(key)
    return ApiKeyCreated(**public.model_dump(), token=token)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: uuid.UUID, user: CurrentUser, db: DbSession, org: OrgSlug = None
) -> Response:
    """Revoke a key immediately. Idempotent: revoking an already-revoked key is a
    no-op that still returns 204."""
    organization = await org_service.resolve_org_for_action(
        db, user=user, slug=org, action=OrgAction.MANAGE_KEYS
    )
    await service.revoke_api_key(db, org=organization, key_id=key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
