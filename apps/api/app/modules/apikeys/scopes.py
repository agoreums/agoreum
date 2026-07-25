"""API key scopes.

A scope is a `resource:action` string that a key may carry. They are the whole
authorisation surface for programmatic access: an API key acts as its owner but is
restricted to exactly the scopes it was granted, so a key minted only to browse the
marketplace cannot place or modify orders even though its owner could in a browser.

Scopes are stored as a text array on the key and validated against this canonical
set in the application, rather than as a database enum: adding a scope here must
never require a migration, and a scope removed from this map is simply refused at
authentication without the stored rows becoming invalid.
"""
from __future__ import annotations

# Ordered so the reference and the management UI list them predictably. `write`
# scopes are deliberately separate from `read`: most integrations need only read.
SCOPES: dict[str, str] = {
    "marketplace:read": "Browse public agents, services, and categories.",
    "agents:read": "Read the agents you own, including drafts.",
    "agents:write": "Create, update, and change the status of your agents.",
    "services:read": "Read the services your agents offer, including drafts.",
    "services:write": "Create, update, and change the status of your services.",
    "orders:read": "Read orders you have placed or received.",
    "orders:write": "Place orders and act on orders you have received.",
}

# The set granted when a caller asks for none explicitly: read-only, marketplace
# only. Chosen so the least-effort key is also the least-privileged one.
DEFAULT_SCOPES: tuple[str, ...] = ("marketplace:read",)


def unknown_scopes(scopes: list[str]) -> list[str]:
    """Return any requested scopes that are not part of the canonical set."""
    return [s for s in scopes if s not in SCOPES]


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    """De-duplicate and order requested scopes to match the canonical listing.

    Order is canonicalised so two keys granted the same rights compare and display
    identically regardless of the order they were requested in.
    """
    if not scopes:
        return list(DEFAULT_SCOPES)
    requested = set(scopes)
    return [s for s in SCOPES if s in requested]
