#!/usr/bin/env python3
"""The well-known documents must be fetchable by a plain HTTP client.

**What this fixes.** Cloudflare's Browser Integrity Check bans on browser
signature and answers `error code: 1010`. Measured on 2026-08-16, it refused the
default `Python-urllib` user agent on every path of this zone, while allowing
python-requests, curl, Go-http-client, node-fetch, axios, a browser, and our own
`agoreum-python/0.2.0`.

**Why that is not cosmetic.** A settlement receipt is only worth more than an
unbacked assertion if somebody who trusts nothing Agoreum says can fetch the
signing key and check it. The intended reader of `/.well-known/` is therefore
software belonging to a stranger, and the most dependency-free way to write a
verifier in Python is the standard library, which is precisely the client that
was refused. Somebody hitting 403 there does not conclude they should set a user
agent. They conclude the receipt cannot be checked, which is the one thing the
design cannot afford.

**Why this file exists rather than a dashboard click.** Configuration that lives
only in a provider's console is invisible to everybody reading this repository,
and this project has already paid for that once: nginx served a week-old
configuration while every deploy went green, because nothing compared what was
running against what was written. A rule nobody can see is a rule nobody can
review, reproduce, or notice the loss of. So the rule is defined here, applied
idempotently, and asserted from outside by
`scripts/check_public_verifiability.py`.

**Why the scope is this narrow.** The exemption covers `/.well-known/` and skips
only the browser integrity check, not the managed ruleset, not rate limiting,
not anything else. Those documents are public, unauthenticated, a few hundred
bytes, served to anyone by design, and already rate limited by nginx at the
origin, so exempting them from a browser-signature heuristic costs nothing that
heuristic was buying. Every other path on the zone keeps it, and the assertion
script checks that rather than assuming it.

Run with no arguments to apply. Safe to run repeatedly.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://api.cloudflare.com/client/v4"
PHASE = "http_request_firewall_custom"

ZONE_NAME = "agoreum.xyz"
EXEMPT_PREFIX = "/.well-known/"

# Matched on to make this idempotent, so re-running never stacks duplicates.
DESCRIPTION = (
    "Skip the browser integrity check for /.well-known/ only. These documents "
    "exist to be fetched by software belonging to people with no account here, "
    "and BIC answers error 1010 to the default Python-urllib user agent."
)


def _token() -> str:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if token:
        return token
    env = REPO / ".env"
    if not env.exists():
        raise SystemExit("no CLOUDFLARE_API_TOKEN in the environment and no .env")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("CLOUDFLARE_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("CLOUDFLARE_API_TOKEN is not in .env")


def cf(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode())


def zone_id() -> str:
    out = cf("/zones")
    for zone in out.get("result") or []:
        if zone["name"] == ZONE_NAME:
            return zone["id"]
    raise SystemExit(f"the token cannot see the {ZONE_NAME} zone: {out.get('errors')}")


def rule() -> dict:
    return {
        "action": "skip",
        # Only the browser integrity check. Naming the product rather than
        # skipping the phase matters: skipping the phase would also drop the
        # managed ruleset for these paths, which is a wider hole than the
        # problem being solved.
        "action_parameters": {"products": ["bic"]},
        "expression": f'(starts_with(http.request.uri.path, "{EXEMPT_PREFIX}"))',
        "description": DESCRIPTION,
        "enabled": True,
    }


def main() -> int:
    zone = zone_id()
    current = cf(f"/zones/{zone}/rulesets/phases/{PHASE}/entrypoint")

    existing: list[dict] = []
    if current.get("success"):
        existing = current["result"].get("rules") or []
    elif [e.get("code") for e in current.get("errors") or []] != [10003]:
        # 10003 is "no entrypoint ruleset yet", which is the ordinary first run.
        print(f"could not read the {PHASE} ruleset: {current.get('errors')}", file=sys.stderr)
        return 1

    # Rebuild rather than append, so a description edit updates in place instead
    # of leaving the old rule behind still doing something slightly different.
    kept = [r for r in existing if r.get("description") != DESCRIPTION]
    if len(kept) == len(existing) and any(
        r.get("expression") == rule()["expression"] for r in existing
    ):
        print("a rule with this expression exists under another description")

    out = cf(
        f"/zones/{zone}/rulesets/phases/{PHASE}/entrypoint",
        method="PUT",
        body={"rules": kept + [rule()]},
    )
    if not out.get("success"):
        print(f"failed to write the rule: {out.get('errors')}", file=sys.stderr)
        return 1

    print(f"applied to zone {ZONE_NAME}:")
    for r in out["result"].get("rules") or []:
        print(f"  {r.get('action')} enabled={r.get('enabled')} {r.get('expression')}")
    print(
        "\nNow assert it from outside with scripts/check_public_verifiability.py, "
        "which also checks the exemption did not spread past /.well-known/."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
