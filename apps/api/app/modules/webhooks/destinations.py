"""Where a webhook is allowed to point.

An endpoint URL is chosen by an organization and fetched by a worker running
inside our network, which is the classic position for server-side request
forgery. Two defences stood before this module existed and both are
load-bearing:

- **https only**, enforced at registration. The cloud metadata service, the
  usual prize, speaks plain HTTP, so it is out of reach.
- **`follow_redirects=False`** on the delivery client. Without it, an endpoint
  that answers on https could redirect to `http://169.254.169.254` and undo the
  first defence entirely.

Neither is about addresses, which is why the check below exists: the protection
above is a side effect of the metadata service's choice of protocol rather than
a decision here, and the delivery record returns `last_status_code` and
`last_error` to the organization, which turns the worker into an oracle for
probing the private network.

The address rule itself lives in `app.core.outbound`, shared with agent domain
verification, which needs the identical answer to the identical question.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from app.core.outbound import DestinationNotAllowed, assert_public_host

__all__ = ["DestinationNotAllowed", "assert_allowed"]


async def assert_allowed(url: str, *, enforce_unresolvable: bool = True) -> None:
    """Raise `DestinationNotAllowed` if this URL points inside our network.

    Checked at registration for immediate feedback, and again at delivery,
    because a name that resolved somewhere public when it was registered can
    resolve somewhere private by the time anything is sent.
    """
    host = urlsplit(url).hostname
    if not host:
        raise DestinationNotAllowed("The webhook URL has no host.")
    await assert_public_host(host, enforce_unresolvable=enforce_unresolvable)
