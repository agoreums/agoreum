"""The catalogue of events a webhook endpoint can subscribe to.

These mirror the event types the platform already raises for in-app notifications,
so a webhook and a bell notification describe the same thing. An endpoint may
subscribe to specific events or to the wildcard "*" to receive all of them.

New event types are added here as the platform raises them; an endpoint subscribed
to "*" picks them up automatically, one subscribed to a list does not until updated.
"""
from __future__ import annotations

WILDCARD = "*"

EVENTS: dict[str, str] = {
    "order.created": "An order was placed.",
    "order.funded": "An order's escrow was funded and confirmed on-chain.",
    "order.started": "The provider began work on an order.",
    "order.delivered": "The provider marked an order delivered.",
    "order.completed": "An order was accepted and funds released.",
    "order.dispute_intent": "A buyer signalled intent to dispute an order.",
    "order.expired": "An order was not funded within its window and expired.",
}


def is_known_event(event_type: str) -> bool:
    return event_type in EVENTS


def unknown_events(events: list[str]) -> list[str]:
    """Requested subscriptions that are neither the wildcard nor a known event."""
    return [e for e in events if e != WILDCARD and e not in EVENTS]


def normalize_events(events: list[str]) -> list[str]:
    """De-duplicate and order requested events. The wildcard collapses the rest."""
    requested = set(events)
    if WILDCARD in requested:
        return [WILDCARD]
    return [e for e in EVENTS if e in requested]


def matches(subscribed: list[str], event_type: str) -> bool:
    return WILDCARD in subscribed or event_type in subscribed
