#!/usr/bin/env python3
"""Every root-level document the API serves must be routed to it by nginx.

This closes a bug found in production twice.

Both times the application was correct. `/.well-known/oauth-protected-resource`
and later `/.well-known/agoreum-receipts.json` were served properly by the API
and returned the marketing site's HTML to the outside world, because nginx sends
everything that does not match `/api/` to the web app and neither path was named
in the config. Nothing failed. The suite was green, the deploy was green, and the
URL was broken for anyone who was not us.

The first fix added one exact-match location, which fixed the instance and left
the category open. Adding a second route reopened it immediately. So the rule is
asserted here instead: enumerate what the application actually registers under
`/.well-known/`, and require a matching location in the nginx config.

Deliberately reads the routes from the app object rather than from a hand-kept
list. A list is another thing to forget to update, and forgetting is the exact
failure being closed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NGINX_CONF = REPO / "infra" / "nginx" / "agoreum.conf"

# `location = /path {`. Only exact matches count. A prefix location would also
# capture paths the API does not serve, so the config uses exact matches and
# this looks for exactly that form.
LOCATION = re.compile(r"^\s*location\s*=\s*(/\.well-known/\S+)\s*\{", re.MULTILINE)


def _walk(routes, prefix: str = ""):
    """Yield every path, descending into included routers.

    FastAPI 0.139 does not flatten `include_router` into `app.routes`. It stores
    an opaque `_IncludedRouter` that carries no `path` of its own, so reading
    `route.path` off the top level silently sees four documentation routes and
    none of the hundred real ones. The first version of this check did exactly
    that and reported zero well-known routes on an app that serves two.

    That is only visible because the caller refuses to pass on an empty result.
    Both branches are kept so this survives a FastAPI version that flattens
    again.
    """
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(inner.routes, prefix + getattr(context, "prefix", ""))
            continue
        path = getattr(route, "path", None)
        if path:
            yield prefix + path


def app_routes() -> set[str]:
    sys.path.insert(0, str(REPO / "apps" / "api"))
    from app.main import app

    return {
        path for path in _walk(app.routes) if path.startswith("/.well-known/")
    }


def nginx_locations(text: str) -> set[str]:
    return set(LOCATION.findall(text))


def main() -> int:
    if not NGINX_CONF.exists():
        print(f"nginx config not found at {NGINX_CONF}", file=sys.stderr)
        return 1

    routes = app_routes()
    located = nginx_locations(NGINX_CONF.read_text(encoding="utf-8"))

    # A run that finds nothing to check must not report success. If the import
    # silently stopped registering these routers, an empty set would compare
    # equal to anything and this would pass while checking nothing.
    if not routes:
        print(
            "found no /.well-known/ routes on the app at all, which means this "
            "check is not looking at what it thinks it is",
            file=sys.stderr,
        )
        return 1

    unrouted = routes - located
    if unrouted:
        print(
            "these routes are served by the API but not routed to it by nginx, "
            "so in production they return the web app's HTML:",
            file=sys.stderr,
        )
        for path in sorted(unrouted):
            print(f"  {path}", file=sys.stderr)
        print(
            f"\nAdd a `location = <path>` block to {NGINX_CONF.relative_to(REPO)} "
            "proxying to http://agoreum_api.",
            file=sys.stderr,
        )
        return 1

    # The reverse direction is a warning, not a failure. A location for a route
    # that no longer exists is dead config rather than a broken URL, and failing
    # on it would block removing an endpoint.
    stale = located - routes
    if stale:
        print("note: nginx routes these to the API, which no longer serves them:")
        for path in sorted(stale):
            print(f"  {path}")

    print(f"{len(routes)} well-known route(s) checked, all routed by nginx:")
    for path in sorted(routes):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
