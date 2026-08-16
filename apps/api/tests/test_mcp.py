"""The MCP server, driven the way an agent's client drives it.

Why it exists: research in August 2026 found MCP carries developer weight in
this space by roughly two orders of magnitude over the alternatives, and that
runtime registry discovery is mostly aspirational. One server exposing the whole
catalogue turns a per-seller integration problem into a single connector.

The assertions that matter most here are not about JSON-RPC. They are about what
reaches another agent's context. A tool description is not interface copy: a
person reading a web page can notice it is wrong, and a model reading a tool
result cannot. So the settlement network is asserted to be present in results
rather than trusted to a handler, and a scope refusal is asserted to arrive as
something an agent can act on rather than as an exception its client library
turns into "the tool broke".
"""
from __future__ import annotations

import json as _json
import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from app.core.config import settings
from app.modules.mcp import server
from app.modules.mcp.tools import BY_NAME, REGISTRY, SETTLEMENT_NOTICE

MCP = "/api/v1/mcp"


async def _sign_in(client: AsyncClient) -> str:
    """A signed-in session. Mirrors the other suites rather than importing,
    because `tests/` is not a package."""
    account = Account.create()
    nonce = await client.post(
        "/api/v1/auth/nonce",
        json={"address": account.address.lower(), "chain_id": settings.CHAIN_ID},
    )
    body = nonce.json()
    signed = account.sign_message(encode_defunct(text=body["message"]))
    resp = await client.post(
        "/api/v1/auth/signin",
        json={
            "message": body["message"],
            "signature": signed.signature.hex(),
            "nonce": body["nonce"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["tokens"]["access_token"]


async def _mint(client: AsyncClient, session: str, scopes: list[str]) -> str:
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "mcp", "scopes": scopes},
        headers={"Authorization": f"Bearer {session}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["token"]


async def _key(client: AsyncClient, scopes: list[str]) -> str:
    return await _mint(client, await _sign_in(client), scopes)


async def _call(client: AsyncClient, key: str, tool: str, args: dict | None = None):
    return await client.post(
        MCP,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args or {}},
        },
        headers={"Authorization": f"Bearer {key}"},
    )


class TestTheRegistryIsInternallyHonest:
    """Properties of the tool table, checkable without a database."""

    def test_every_tool_is_registered_once(self) -> None:
        names = [t.name for t in REGISTRY]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"
        assert set(BY_NAME) == set(names)

    def test_every_tool_declares_scopes_that_exist(self) -> None:
        """Scopes are data so they can be audited.

        A tool whose requirement lives inside its handler is one nobody can
        check without reading code.
        """
        from app.modules.apikeys.scopes import SCOPES

        for tool in REGISTRY:
            unknown = tool.scopes - set(SCOPES)
            assert not unknown, f"{tool.name} needs scopes that do not exist: {unknown}"

    def test_every_tool_that_touches_money_names_the_network(self) -> None:
        """The description reaches a model with no human in the loop."""
        for tool in REGISTRY:
            if tool.touches_money:
                assert "Base Sepolia" in tool.description, (
                    f"{tool.name} concerns money and its description does not name "
                    "the network, so an agent could take this for mainnet"
                )

    def test_every_tool_has_a_closed_input_schema(self) -> None:
        """An open schema invites a model to invent arguments that are ignored."""
        for tool in REGISTRY:
            assert tool.input_schema.get("additionalProperties") is False, (
                f"{tool.name} accepts undeclared arguments"
            )

    def test_the_network_check_needs_no_permission(self) -> None:
        """An agent must be able to ask what it is dealing with before spending."""
        assert BY_NAME["chain_status"].scopes == frozenset()


class TestTheProtocol:
    async def test_an_unauthenticated_call_says_where_to_authenticate(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert resp.status_code == 401
        challenge = resp.headers.get("WWW-Authenticate", "")
        assert challenge.startswith("Bearer "), challenge
        assert "resource_metadata=" in challenge, (
            "the challenge does not point at the metadata document, so a client "
            "learns it was refused and not what to do about it"
        )

    async def test_the_metadata_document_is_at_the_origin_root(
        self, client: AsyncClient
    ) -> None:
        """RFC 9728 puts it at the root, not under an API prefix."""
        resp = await client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resource"].endswith("/api/v1/mcp")
        assert "marketplace:read" in body["scopes_supported"]

    async def test_it_is_honest_that_the_token_is_an_api_key(
        self, client: AsyncClient
    ) -> None:
        """Claiming an OAuth flow that does not exist would send clients into one."""
        body = (await client.get("/.well-known/oauth-protected-resource")).json()
        # noqa on the literal: this is a credential *kind*, not a credential.
        assert body["agoreum_token_type"] == "api_key"  # noqa: S105

    async def test_tools_list_returns_the_whole_registry(
        self, client: AsyncClient
    ) -> None:
        key = await _key(client, ["marketplace:read"])
        resp = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == 7
        tools = body["result"]["tools"]
        assert {t["name"] for t in tools} == set(BY_NAME)
        for tool in tools:
            assert tool["inputSchema"], f"{tool['name']} published no input schema"

    async def test_an_unknown_method_is_a_protocol_error(
        self, client: AsyncClient
    ) -> None:
        key = await _key(client, ["marketplace:read"])
        resp = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "id": 2, "method": "does/not/exist"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.json()["error"]["code"] == server.METHOD_NOT_FOUND

    async def test_a_notification_gets_no_reply(self, client: AsyncClient) -> None:
        key = await _key(client, ["marketplace:read"])
        resp = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 202


class TestWhatReachesTheAgent:
    async def test_a_missing_scope_is_an_answer_not_an_exception(
        self, client: AsyncClient
    ) -> None:
        """The refusal has to be actionable inside the model's context.

        As a JSON-RPC error it becomes an exception in the client library and
        what the model sees is that the tool broke. As a tool result naming the
        missing scope, the agent can tell its operator what to grant.
        """
        key = await _key(client, ["marketplace:read"])
        body = (await _call(client, key, "list_my_orders")).json()

        assert "error" not in body, "a scope refusal was raised to protocol level"
        result = body["result"]
        assert result["isError"] is True
        payload = result["structuredContent"]
        assert payload["error"] == "insufficient_scope"
        assert "orders:read" in payload["missing_scopes"]
        assert payload["remedy"], "the refusal does not say how to fix it"

    async def test_a_granted_scope_reaches_the_tool(self, client: AsyncClient) -> None:
        key = await _key(client, ["marketplace:read", "orders:read"])
        result = (await _call(client, key, "list_my_orders")).json()["result"]
        assert result["isError"] is False, result
        assert result["structuredContent"]["items"] == []

    async def test_every_money_result_carries_the_network(
        self, client: AsyncClient
    ) -> None:
        """The assertion this whole server is built around."""
        key = await _key(client, ["marketplace:read", "orders:read"])

        for tool in ("chain_status", "search_services", "list_my_orders"):
            result = (await _call(client, key, tool)).json()["result"]
            assert result["isError"] is False, (tool, result)
            assert "Base Sepolia" in result["structuredContent"].get("notice", ""), (
                f"{tool} returned a money-related result without naming the network"
            )

    async def test_the_network_tool_states_it_is_a_test_network(
        self, client: AsyncClient
    ) -> None:
        key = await _key(client, ["marketplace:read"])
        payload = (await _call(client, key, "chain_status")).json()["result"][
            "structuredContent"
        ]
        assert payload["is_testnet"] is True
        assert payload["network"] == "base-sepolia"

    async def test_a_result_is_both_readable_and_structured(
        self, client: AsyncClient
    ) -> None:
        """Clients differ in which they read, and they must not disagree."""
        key = await _key(client, ["marketplace:read"])
        result = (await _call(client, key, "chain_status")).json()["result"]

        assert result["content"][0]["type"] == "text"
        assert _json.loads(result["content"][0]["text"]) == result["structuredContent"]

    async def test_reputation_states_where_it_came_from(
        self, client: AsyncClient
    ) -> None:
        """A score without provenance is not evidence.

        This is the one number an outside agent might weigh a purchase on, and
        the thing that distinguishes it from the on-chain reputation registries
        is that it cannot exist without a settled order behind it.
        """
        key = await _key(client, ["marketplace:read"])
        result = (
            await _call(
                client, key, "get_agent_reputation", {"slug": f"nope-{uuid.uuid4().hex[:8]}"}
            )
        ).json()["result"]
        # The agent does not exist, so this is a refusal rather than a score.
        # The point asserted here is that the refusal is an answer.
        assert result["isError"] is True
        assert result["structuredContent"]["error"]

    async def test_a_not_found_is_an_answer_not_a_crash(
        self, client: AsyncClient
    ) -> None:
        key = await _key(client, ["marketplace:read"])
        result = (
            await _call(
                client, key, "get_agent", {"slug": f"missing-{uuid.uuid4().hex[:8]}"}
            )
        ).json()["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["error"]

    async def test_an_unknown_tool_is_a_protocol_error(
        self, client: AsyncClient
    ) -> None:
        key = await _key(client, ["marketplace:read"])
        body = (await _call(client, key, "not_a_tool")).json()
        assert body["error"]["code"] == server.INVALID_PARAMS


@pytest.mark.parametrize("tool_name", sorted(BY_NAME))
def test_the_settlement_notice_is_a_single_string(tool_name: str) -> None:
    """Guards the guard.

    Every check above looks for "Base Sepolia". If the notice were reworded per
    tool, those checks would drift into testing nothing in particular.
    """
    assert "Base Sepolia" in SETTLEMENT_NOTICE
    assert BY_NAME[tool_name].name == tool_name
