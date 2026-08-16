#!/usr/bin/env python3
"""A stranger's software must be able to check an Agoreum receipt.

This asserts the property the receipts design rests on, from outside, against
the real deployed site, using no credentials at all. That is deliberate: the
person this protects has no account here, so a check holding an API key is
checking something easier than the real thing.

Three things have to be true at once, and each has already failed alone.

1. **The document is routed to the API.** For a week nginx sent every
   `/.well-known/` path to the web application, which answered the marketing
   site's HTML. The application was correct the whole time and the URL was broken
   for everybody who was not us.
2. **The API is holding a signing key.** Without one it still issues receipts,
   still carries every coordinate, and only `signature` is null, so losing the
   key degrades the product silently rather than breaking it.
3. **A plain HTTP client can actually fetch it.** Cloudflare's browser integrity
   check answered `error code: 1010` to the default Python-urllib user agent
   until 2026-08-16.

The third is the one worth explaining, because it is the least obvious and was
found by accident. The verifier this is all for is software, written by somebody
who has no reason to trust us, most cheaply with a standard library. A 403 does
not read to that person as "configure a user agent". It reads as "this cannot be
verified", which makes the receipt worth exactly what the unbacked ERC-8004
records are worth.

The negative half matters as much as the positive: an exemption that quietly
covered the whole zone would look identical from the well-known documents alone,
so paths that must still be protected are checked in the same run.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "https://agoreum.xyz"
KEY_DOCUMENT = f"{BASE}/.well-known/agoreum-receipts.json"

# The exact client the browser integrity check used to refuse. Hard-coded rather
# than left to the default so this keeps testing the real case even if the
# runtime's default user agent changes.
PLAIN_CLIENT = "Python-urllib/3.14"

MUST_BE_PUBLIC = (
    KEY_DOCUMENT,
    f"{BASE}/.well-known/oauth-protected-resource",
)

# The exemption is meant to be narrow. `/.well-knownnot/` is included because a
# prefix match written slightly wrong would let it through, and that is the kind
# of near miss nobody notices by reading the expression.
MUST_STILL_BE_PROTECTED = (
    f"{BASE}/en",
    f"{BASE}/api/v1/health/ready",
    f"{BASE}/.well-knownnot/receipts.json",
)


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": PLAIN_CLIENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> int:
    failures: list[str] = []

    for url in MUST_BE_PUBLIC:
        status, _ = fetch(url)
        if status != 200:
            failures.append(
                f"{url} answered {status} to {PLAIN_CLIENT}. A verifier with no "
                "account cannot read it, so a receipt cannot be checked."
            )

    status, body = fetch(KEY_DOCUMENT)
    if status == 200:
        try:
            document = json.loads(body)
        except json.JSONDecodeError:
            failures.append(f"{KEY_DOCUMENT} did not return JSON: {body[:120]!r}")
        else:
            keys = document.get("keys") or []
            if not keys:
                failures.append(
                    "the key document carries no signing key, so receipts are "
                    "being issued unsigned while everything else looks correct"
                )
            elif not keys[0].get("kid") or not keys[0].get("x"):
                failures.append(f"the published key is incomplete: {keys[0]}")
            if "chain" not in (document.get("verification") or "").lower():
                failures.append(
                    "the key document no longer tells a verifier that the chain "
                    "is the authority, which is the point of the receipt"
                )

    for url in MUST_STILL_BE_PROTECTED:
        status, _ = fetch(url)
        if status == 200:
            failures.append(
                f"{url} is reachable by {PLAIN_CLIENT}. The browser integrity "
                "check exemption was meant to cover /.well-known/ only, and it "
                "has spread."
            )

    if failures:
        print("public verifiability is broken:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    keys = json.loads(fetch(KEY_DOCUMENT)[1])["keys"]
    print(
        f"a plain client can fetch the key document and read key {keys[0]['kid']}, "
        "and the exemption has not spread past /.well-known/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
