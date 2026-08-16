"""The machine-readable contract, published rather than hidden.

Every route in this service is already public: the repository is public, so the
routers are readable by anyone, and the three official SDKs spell out the paths
they call. Withholding the OpenAPI document therefore hid nothing from anybody
willing to look, while costing every integrator the ability to generate a client
for a language we do not ship, import the API into a tool, or check their code
against the contract instead of against our prose.

That is the wrong trade for a product whose entire premise is that software,
not people, does the buying and selling.

It does not follow that everything belongs in the published document. There is a
real difference between "an attacker can find this" and "we advertise this as
part of the supported surface". Operator endpoints are not part of the contract
an integrator builds against, they change without notice, and listing them
invites use that will break. So the published document is scoped to the surface
we intend third parties to depend on, and the exclusion is asserted by a test
rather than maintained by memory.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Tags an integrator builds against. Anything tagged outside this set is left
# out of the published document.
#
# An allowlist rather than a denylist, deliberately. With a denylist, a new
# operator endpoint is published unless somebody remembers to exclude it, and
# the failure is silent and outward-facing. With an allowlist the same mistake
# leaves a new public endpoint undocumented, which is visible the moment anyone
# looks for it and harms nobody.
PUBLIC_TAGS: frozenset[str] = frozenset(
    {
        "authentication",
        "identity",
        "marketplace",
        "agents",
        "services",
        "orders",
        "reputation",
        "subscriptions",
        "api-keys",
        "webhooks",
        # A receipt is meant to be handed to a third party and checked, so the
        # endpoint that issues it belongs in the contract an integrator reads.
        "receipts",
    }
)

# Excluded, with the reason, so a reader can tell a decision from an oversight.
EXCLUDED_TAGS: dict[str, str] = {
    "administration": "operator only, gated on an admin role, changes without notice",
    "dashboard": "shapes data for our own interface and is not a stable contract",
    "analytics": "internal reporting, not part of what anyone integrates against",
    "health": "operational probes for our own monitoring, documented in the runbook",
    "notifications": "provider webhook receivers we do not invite callers to post to",
    # All fourteen handlers take a session, so no API key can reach any of them.
    # Publishing them would document a surface that answers 401 to every reader
    # of the document, which is worse than omitting them.
    "organizations": "session only; account and team management, not an integration surface",
    # Both MCP routes are already `include_in_schema=False`, so this entry only
    # satisfies the classification check. It is not a REST contract: MCP clients
    # discover tools through `tools/list` and authentication through the RFC 9728
    # metadata document, and an OpenAPI operation describing a JSON-RPC envelope
    # would tell a generator nothing useful about what the endpoint accepts.
    "mcp": "JSON-RPC endpoint; described by tools/list and RFC 9728 metadata, not by OpenAPI",
}


def public_openapi(app: FastAPI) -> dict[str, Any]:
    """The OpenAPI document for the supported third-party surface."""
    document = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    paths = document.get("paths", {})
    kept: dict[str, Any] = {}
    for path, operations in paths.items():
        public_ops = {
            method: operation
            for method, operation in operations.items()
            if _is_public(operation)
        }
        if public_ops:
            kept[path] = public_ops
    document["paths"] = kept

    # Schemas are left whole. Pruning to only those reachable from the kept
    # paths would mean walking every $ref transitively, and getting that subtly
    # wrong produces a document that validates but cannot be generated from,
    # which is worse than one carrying a few unused definitions.
    document["tags"] = [
        tag for tag in document.get("tags", []) if tag.get("name") in PUBLIC_TAGS
    ]
    return document


def _is_public(operation: Any) -> bool:
    if not isinstance(operation, dict):
        # OpenAPI puts non-operation keys such as "parameters" alongside methods.
        return False
    tags = operation.get("tags") or []
    return any(tag in PUBLIC_TAGS for tag in tags)
