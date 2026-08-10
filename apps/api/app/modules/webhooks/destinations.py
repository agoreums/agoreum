"""Where a webhook is allowed to point.

An endpoint URL is chosen by an organization and fetched by a worker running
inside our network, which is the classic position for server-side request
forgery. Two defences already stood before this module existed and both are
load-bearing:

- **https only**, enforced at registration. The cloud metadata service, the
  usual prize, speaks plain HTTP, so it is out of reach.
- **`follow_redirects=False`** on the delivery client. Without it, an endpoint
  that answers on https could redirect to `http://169.254.169.254` and undo the
  first defence entirely.

What was missing is any check on *which* address the URL reaches. That mattered
less than it looks, because reaching an internal service also requires it to
speak TLS, but the delivery record exposes `last_status_code` and `last_error`
back to the organization, which turns the worker into an oracle for probing the
private network. Neither of the existing defences is about addresses, and both
would keep working if this check did not exist, which is precisely why it is
worth having: the protection today is a side effect of the metadata service's
choice of protocol, not of anything we decided.

Checked at registration for immediate feedback, and again at delivery because
the name can resolve somewhere else by then.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.logging import get_logger

logger = get_logger(__name__)


class DestinationNotAllowed(Exception):
    """The URL resolves somewhere a webhook must not reach."""


def _is_forbidden(address: str) -> bool:
    """Whether an address belongs to our own network rather than the internet."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
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


def resolved_addresses(host: str) -> list[str]:
    """Every address a host resolves to, or an empty list if it does not."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def assert_allowed(url: str, *, enforce_unresolvable: bool = True) -> None:
    """Raise `DestinationNotAllowed` if this URL points inside our network.

    Every address the host resolves to is checked, not just the first. A name
    answering with one public and one private address would otherwise pass here
    and connect to whichever the client picked.

    `enforce_unresolvable=False` is for registration, where a name that does not
    resolve yet is a plausible mistake rather than an attack, and where delivery
    will check again anyway. Delivery leaves it True, so an unresolvable host is
    refused rather than attempted.
    """
    host = urlsplit(url).hostname
    if not host:
        raise DestinationNotAllowed("The webhook URL has no host.")

    # An address literal never reaches DNS, so check it directly.
    if _is_forbidden(host):
        raise DestinationNotAllowed(
            "A webhook cannot point at a private or loopback address."
        )

    addresses = resolved_addresses(host)
    if not addresses:
        if enforce_unresolvable:
            raise DestinationNotAllowed(f"{host} does not resolve.")
        return

    forbidden = [a for a in addresses if _is_forbidden(a)]
    if forbidden:
        logger.warning(
            "webhook_destination_blocked",
            extra={"host": host, "resolved_to": forbidden},
        )
        raise DestinationNotAllowed(
            "A webhook cannot point at a host that resolves to a private or "
            "loopback address."
        )
