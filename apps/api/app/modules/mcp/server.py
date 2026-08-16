"""JSON-RPC dispatch for the MCP endpoint.

Kept separate from the HTTP layer so the protocol behaviour can be tested
without a transport, and so the transport can change without touching it.

Two decisions worth stating.

**Errors come back as tool results, not as JSON-RPC errors, when the tool ran
and refused.** A scope refusal is information the calling agent can act on: it
tells the agent's operator which scope to grant. Returned as a protocol-level
error it becomes an exception in a client library, and what reaches the model is
"the tool broke". Returned as an `isError` result with the missing scope named,
the agent can say what it needs. Protocol errors are reserved for the protocol
being wrong: unknown method, malformed request, unknown tool.

**The handshake is accepted but nothing depends on it.** The 2026-07-28 spec
made the core stateless and dropped the initialize handshake, but deployed
clients still send it and will for some time. Answering it costs nothing;
requiring it would exclude newer clients. No server state is kept either way.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AgoreumError
from app.core.logging import get_logger
from app.modules.mcp.tools import BY_NAME, REGISTRY, SETTLEMENT_NOTICE, Tool

logger = get_logger(__name__)

PROTOCOL_VERSION = "2026-07-28"
SERVER_INFO = {"name": "agoreum", "title": "Agoreum marketplace", "version": "0.1.0"}

# JSON-RPC reserved codes. Only these are used; application-level refusals are
# tool results, for the reason in the module docstring.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    """An MCP tool result.

    Both shapes are sent: `content` for clients that read text, and
    `structuredContent` for those that read JSON. Sending only one loses half
    the clients, and they cannot disagree because both are rendered from the
    same object.
    """
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "title": tool.title,
            "description": tool.description,
            "inputSchema": tool.input_schema,
            # Not part of the spec, and useful: an operator wiring this up can
            # see which scopes a key needs without reading our documentation.
            "_meta": {"agoreum/scopes": sorted(tool.scopes)},
        }
        for tool in REGISTRY
    ]


async def dispatch(
    message: dict[str, Any], *, principal: Principal, db: AsyncSession
) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "Expected a JSON-RPC 2.0 request.")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # A notification has no id and expects no response.
    is_notification = "id" not in message

    if method == "initialize":
        return None if is_notification else _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Agoreum is a marketplace where agents publish services and "
                    "settle in USDC through on-chain escrow. " + SETTLEMENT_NOTICE
                ),
            },
        )

    if method in {"notifications/initialized", "initialized"}:
        return None

    if method == "ping":
        return None if is_notification else _result(request_id, {})

    if method == "tools/list":
        if is_notification:
            return None
        return _result(
            request_id,
            {
                "tools": tool_descriptors(),
                # The catalogue changes constantly, so a cached list goes stale
                # in a way a static tool set would not.
                "ttlMs": 60_000,
                "cacheScope": "session",
            },
        )

    if method == "tools/call":
        if is_notification:
            return None
        return await _call_tool(request_id, params, principal=principal, db=db)

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")


async def _call_tool(
    request_id: Any, params: dict[str, Any], *, principal: Principal, db: AsyncSession
) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if not isinstance(name, str) or name not in BY_NAME:
        return _error(request_id, INVALID_PARAMS, f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        return _error(request_id, INVALID_PARAMS, "arguments must be an object.")

    tool: Tool = BY_NAME[name]

    missing = sorted(tool.scopes - principal.scopes)
    if missing:
        # A refusal the agent can act on, rather than an exception its client
        # library turns into "the tool broke".
        return _result(
            request_id,
            _tool_result(
                {
                    "error": "insufficient_scope",
                    "message": (
                        f"This API key is missing the scope(s) required by "
                        f"{name}: {', '.join(missing)}."
                    ),
                    "missing_scopes": missing,
                    "remedy": (
                        "Mint a key with these scopes selected. Scopes are "
                        "granted only by naming them at mint time."
                    ),
                },
                is_error=True,
            ),
        )

    try:
        payload = await tool.handler(db, principal, **arguments)
    except AgoreumError as exc:
        # The application's own refusals are answers, not faults: not found,
        # conflict, permission. The agent should see what happened.
        return _result(
            request_id,
            _tool_result(
                {"error": exc.code, "message": str(exc.message)}, is_error=True
            ),
        )
    except TypeError as exc:
        return _error(request_id, INVALID_PARAMS, f"Invalid arguments for {name}: {exc}")
    except Exception as exc:  # pragma: no cover - genuinely unexpected
        logger.exception("mcp_tool_failed", extra={"tool": name})
        return _error(
            request_id, INTERNAL_ERROR, f"{type(exc).__name__} while running {name}"
        )

    if tool.touches_money and "notice" not in payload:
        # Belt and braces. The handlers add this themselves; this makes it
        # impossible for a new one to forget, because the omission would
        # otherwise be invisible until an agent had already been misled.
        payload = {**payload, "notice": SETTLEMENT_NOTICE}

    return _result(request_id, _tool_result(payload))
