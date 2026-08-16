"""The MCP transport: one POST endpoint, plus the metadata a client needs to
authenticate against it.

Streamable HTTP only. The older HTTP+SSE transport is deprecated in the current
spec and building on it now would be building something with a known expiry.

Authentication reuses the existing scoped API keys rather than inventing a
second credential system. The spec expects an OAuth 2.1 resource server, and
that is worth having, but the useful half is available immediately: a key
presented as a bearer token, a 401 that tells the client where to look, and a
403 that names the missing scope. A client that can paste a key works today, and
the metadata document is the same one a full OAuth flow will need.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.api.deps import DbSession, get_principal
from app.core.config import settings
from app.core.errors import AuthenticationError
from app.modules.mcp import server

router = APIRouter(tags=["mcp"])

# RFC 9728 requires this at the origin root, not under an API prefix, so it is
# mounted on the application directly rather than on the versioned router.
well_known = APIRouter(tags=["mcp"])

_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"


def _challenge(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    return (
        f'Bearer resource_metadata="{base}{_RESOURCE_METADATA_PATH}", '
        'scope="marketplace:read orders:read orders:write agents:read"'
    )


@well_known.get(
    _RESOURCE_METADATA_PATH,
    include_in_schema=False,
    summary="Where to authenticate for the MCP endpoint",
)
async def protected_resource_metadata(request: Request) -> dict[str, Any]:
    """RFC 9728 metadata.

    Served whether or not a full authorization server is in place, because it is
    how a client discovers what to send. Today it points at the dashboard, which
    is where a key is actually minted, rather than claiming an OAuth flow that
    does not exist yet.
    """
    base = str(request.base_url).rstrip("/")
    return {
        "resource": f"{base}{settings.API_V1_PREFIX}/mcp",
        "scopes_supported": [
            "marketplace:read",
            "agents:read",
            "agents:write",
            "services:read",
            "services:write",
            "orders:read",
            "orders:write",
        ],
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://agoreum.xyz/docs/api",
        # Stated plainly rather than implied by omission: today the bearer token
        # is an Agoreum API key, not an OAuth access token.
        "resource_signing_alg_values_supported": [],
        "agoreum_token_type": "api_key",
        "agoreum_token_instructions": (
            "Mint an API key in the dashboard and send it as "
            "Authorization: Bearer ak_..., or as X-API-Key."
        ),
    }


@router.post(
    "/mcp",
    include_in_schema=False,
    summary="Model Context Protocol endpoint",
)
async def mcp_endpoint(request: Request, response: Response, db: DbSession) -> Any:
    """Handle a single JSON-RPC message or a batch of them.

    Authentication is resolved here rather than as a dependency so that a
    missing credential produces the `WWW-Authenticate` challenge the MCP spec
    requires, which is what tells a client where to go rather than simply that
    it was refused.
    """
    try:
        body = await request.json()
    except Exception:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": server.PARSE_ERROR, "message": "Body is not valid JSON."},
        }

    try:
        principal = await _principal_for(request, db)
    except AuthenticationError as exc:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.headers["WWW-Authenticate"] = _challenge(request)
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": server.INVALID_REQUEST, "message": str(exc.message)},
        }

    if isinstance(body, list):
        # A batch. Notifications return nothing, so a batch of only
        # notifications correctly produces an empty response.
        replies = [
            reply
            for message in body
            if (reply := await server.dispatch(message, principal=principal, db=db))
            is not None
        ]
        if not replies:
            response.status_code = status.HTTP_202_ACCEPTED
            return None
        return replies

    reply = await server.dispatch(body, principal=principal, db=db)
    if reply is None:
        response.status_code = status.HTTP_202_ACCEPTED
        return None
    return reply


async def _principal_for(request: Request, db: DbSession):
    """Resolve the caller from either header form the API already accepts."""
    from fastapi.security import HTTPAuthorizationCredentials

    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    credentials = (
        HTTPAuthorizationCredentials(scheme=scheme, credentials=token)
        if scheme.lower() == "bearer" and token
        else None
    )
    return await get_principal(
        request=request,
        credentials=credentials,
        api_key_value=request.headers.get("X-API-Key"),
        db=db,
    )
