"""API key management endpoints.

These are authenticated by the browser session (a signed-in user managing their own
keys), not by an API key. The keys they mint are what authenticate the programmatic
API; see `app.api.deps.ApiKeyPrincipal`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.modules.apikeys import service
from app.modules.apikeys.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyList,
    ApiKeyPublic,
    ScopeCatalog,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("/scopes", response_model=ScopeCatalog, summary="Available API key scopes")
async def scopes() -> ScopeCatalog:
    """The scopes a key may be granted. Public so the docs and the key-creation UI
    can render the catalogue without a session."""
    return ScopeCatalog()


@router.get("", response_model=ApiKeyList, summary="Your API keys")
async def list_keys(user: CurrentUser, db: DbSession) -> ApiKeyList:
    keys = await service.list_api_keys(db, user=user)
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
    payload: ApiKeyCreate, user: CurrentUser, db: DbSession
) -> ApiKeyCreated:
    """Mint a key. The plaintext token is in the response and is shown only here —
    it cannot be retrieved again, only replaced."""
    key, token = await service.create_api_key(
        db,
        user=user,
        name=payload.name,
        scopes=payload.scopes,
        expires_in_days=payload.expires_in_days,
    )
    # The ORM row has no `token` attribute, so validate it to the public shape
    # first, then attach the plaintext secret — the one and only time it is shown.
    public = ApiKeyPublic.model_validate(key)
    return ApiKeyCreated(**public.model_dump(), token=token)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    """Revoke a key immediately. Idempotent: revoking an already-revoked key is a
    no-op that still returns 204."""
    await service.revoke_api_key(db, user=user, key_id=key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
