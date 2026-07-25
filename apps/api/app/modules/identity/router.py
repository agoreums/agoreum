"""Caller identity for the programmatic API.

`GET /me` answers "who is this credential, and what may it do" — the first call an
SDK makes to confirm a key works and to discover which scopes it carries. It accepts
either an API key or a browser session, so the same endpoint serves both.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentPrincipal

router = APIRouter(tags=["identity"])


class AuthContext(BaseModel):
    # "api_key" or "session" — how this request was authenticated.
    method: str
    scopes: list[str]
    # Present only when authenticated by an API key.
    api_key_prefix: str | None = None


class Me(BaseModel):
    id: uuid.UUID
    username: str | None
    display_name: str | None
    primary_address: str
    role: str
    created_at: datetime
    auth: AuthContext


@router.get("/me", response_model=Me, summary="Who am I")
async def me(principal: CurrentPrincipal) -> Me:
    user = principal.user
    return Me(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        primary_address=user.primary_address,
        role=str(user.role),
        created_at=user.created_at,
        auth=AuthContext(
            method="api_key" if principal.via_api_key else "session",
            scopes=sorted(principal.scopes),
            api_key_prefix=principal.api_key.prefix if principal.api_key else None,
        ),
    )
