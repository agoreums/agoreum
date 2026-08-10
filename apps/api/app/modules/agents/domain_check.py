"""Proof-of-domain-control checks.

Both methods perform a real lookup. Neither ever reports success without having
observed the token, because a false positive here would let anyone claim any
domain and inherit the trust that carries.

The well-known method fetches a URL derived from user input, so it is a
server-side request forgery risk by construction. It is defended by resolving
the host first and refusing any address that is not publicly routable, without
that, an agent could point verification at an internal service or a cloud
metadata endpoint and use this service as a proxy into the private network.
"""
from __future__ import annotations

import asyncio

from app.core import outbound
from app.core.logging import get_logger

logger = get_logger(__name__)

DNS_TIMEOUT_SECONDS = 5.0
HTTP_TIMEOUT_SECONDS = 8.0
# A proof file has no reason to be large. Capping the read stops a hostile host
# from streaming indefinitely into this process.
MAX_RESPONSE_BYTES = 4096

WELL_KNOWN_PATH = "/.well-known/agoreum-verification"


def _is_public_address(host: str) -> tuple[bool, str | None]:
    """Resolve a host and confirm every address it maps to is publicly routable.

    The rule lives in `app.core.outbound`, shared with webhook delivery. It was
    written here first and independently a second time for webhooks, which is
    how a security boundary drifts: one copy gains a case and the other does
    not. Kept as a thin name because the call sites read better for it.
    """
    return outbound.check_host(host)


async def check_dns_txt(domain: str, token: str) -> tuple[bool, str | None]:
    """Look for the token in the domain's TXT records."""
    try:
        import dns.asyncresolver
        import dns.exception
    except ImportError:
        return False, "DNS verification is unavailable on this deployment."

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = DNS_TIMEOUT_SECONDS
    resolver.timeout = DNS_TIMEOUT_SECONDS

    try:
        answers = await resolver.resolve(domain, "TXT")
    except dns.resolver.NXDOMAIN:
        return False, "That domain does not exist."
    except dns.resolver.NoAnswer:
        return False, "That domain has no TXT records yet."
    except dns.exception.Timeout:
        return False, "The DNS lookup timed out. Try again shortly."
    except Exception as exc:
        logger.warning("dns_lookup_failed", extra={"error_type": type(exc).__name__})
        return False, "The DNS lookup failed."

    for record in answers:
        # A TXT record can be split into multiple strings; join before comparing
        # or a long token would never match.
        value = "".join(
            part.decode("utf-8", "ignore") if isinstance(part, bytes) else str(part)
            for part in record.strings
        )
        if value.strip() == token:
            return True, None

    return False, "The verification token was not found in the TXT records."


async def check_well_known(domain: str, token: str) -> tuple[bool, str | None]:
    """Fetch the well-known path over HTTPS and look for the token."""
    import httpx

    # Resolution happens off the event loop: getaddrinfo blocks.
    public, error = await asyncio.to_thread(_is_public_address, domain)
    if not public:
        return False, error

    url = f"https://{domain}{WELL_KNOWN_PATH}"

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            # Redirects are not followed: a redirect could send this request to
            # an internal address that the pre-flight check never saw.
            follow_redirects=False,
        ) as client:
            response = await client.get(url, headers={"User-Agent": "Agoreum/1.0"})
    except httpx.TimeoutException:
        return False, "The request timed out. Check the file is reachable."
    except httpx.HTTPError as exc:
        logger.info(
            "well_known_fetch_failed", extra={"error_type": type(exc).__name__}
        )
        return False, f"Could not reach {url}."

    if response.status_code != 200:
        return False, f"{url} returned HTTP {response.status_code}."

    body = response.content[:MAX_RESPONSE_BYTES].decode("utf-8", "ignore")
    if token in body.strip():
        return True, None

    return False, "The verification token was not found at that URL."
