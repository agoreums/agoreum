"""Whether an outbound request may reach a host somebody else chose.

The platform fetches destinations chosen by other people in two places: webhook
delivery, and agent domain verification. Both run inside our network, so both
are server-side request forgery positions, and both need the same answer to the
same question.

It was implemented twice, independently, with the same reasoning written out
both times. That is the hazard this module exists to remove: a security
boundary in two copies drifts the moment one is improved. The webhook copy was
also missing something the older one had, which is the point.

Two properties carried over from the better of the two, because each was
learned rather than guessed:

- **Every resolved address is checked, not just the first.** A host answering
  with one public and one private address would otherwise pass, and the client
  would connect to whichever it picked.
- **Resolution happens off the event loop.** `getaddrinfo` blocks, and a slow
  or hostile nameserver would otherwise stall every other request in the
  process, not merely this one.

What this cannot do is close the gap between resolving a name and connecting to
it. A name can answer differently on the second lookup. Callers narrow that by
refusing redirects, so a checked connection cannot be handed onwards, and by
re-checking at the moment of use rather than only at registration.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket

from app.core.logging import get_logger

logger = get_logger(__name__)


class DestinationNotAllowed(Exception):
    """The host resolves somewhere an outbound request must not reach."""


def is_forbidden_address(address: str) -> bool:
    """Whether an address belongs to our own network rather than the internet."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        # Unparseable is not automatically hostile, but it is unusable, and the
        # caller decides what to do with a host that resolves to nothing valid.
        return False

    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolved_addresses(host: str, port: int | None = None) -> list[str]:
    """Every address a host resolves to, or an empty list if it does not.

    Blocking. Call through `assert_public_host` from async code.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def check_host(host: str) -> tuple[bool, str | None]:
    """Whether this host is safe to reach, and why not when it is not.

    Blocking, and returns rather than raises, for callers that report a reason
    to a person filling in a form.
    """
    if not host:
        return False, "No host was given."

    # An address literal never reaches DNS, so it is checked directly. Without
    # this, `https://10.0.0.5/` would depend on getaddrinfo echoing it back.
    if is_forbidden_address(host):
        return False, "That address is private or loopback."

    addresses = resolved_addresses(host)
    if not addresses:
        return False, "That host could not be resolved."

    forbidden = [a for a in addresses if is_forbidden_address(a)]
    if forbidden:
        logger.warning(
            "outbound_destination_blocked",
            extra={"host": host, "resolved_to": forbidden},
        )
        return False, "That host resolves to a non-public address."

    return True, None


async def assert_public_host(host: str, *, enforce_unresolvable: bool = True) -> None:
    """Raise `DestinationNotAllowed` unless this host is safe to reach.

    `enforce_unresolvable=False` accepts a name that does not resolve yet, for
    registration paths where that is a likelier mistake than an attack and where
    the destination is checked again before anything is sent.
    """
    if not host:
        raise DestinationNotAllowed("No host was given.")

    if is_forbidden_address(host):
        raise DestinationNotAllowed("That address is private or loopback.")

    addresses = await asyncio.to_thread(resolved_addresses, host)
    if not addresses:
        if enforce_unresolvable:
            raise DestinationNotAllowed(f"{host} does not resolve.")
        return

    forbidden = [a for a in addresses if is_forbidden_address(a)]
    if forbidden:
        logger.warning(
            "outbound_destination_blocked",
            extra={"host": host, "resolved_to": forbidden},
        )
        raise DestinationNotAllowed(
            "That host resolves to a private or loopback address."
        )
