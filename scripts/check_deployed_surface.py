#!/usr/bin/env python3
"""Does production actually serve what this repository says it does.

Two failures on 2026-08-22, in this order, and each needed a different check.

**The route was not there.** `settlement-options` merged, the deploy job
reported success, and the endpoint 404ed. The job had genuinely succeeded; it
was simply not the deploy. A check that read "the newest run on main" had
matched a scheduled uptime job.

**The route was there and returned 500 on every request.** Enumerating paths
would have called that a pass. The endpoint existed, was correctly named, and
crashed on the first line that read configuration.

So this does both, in that order, because they fail differently:

1. Compare the repository's routes against the deployed OpenAPI. Anything here
   and not there is a deploy that did not land.
2. Actually call the read-only ones as a signed-in user and refuse a 5xx.
   Existing is not working, and only the second question catches that.

Read only. Every request is a GET, and the account used is the operator's own.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE = os.environ.get("AGOREUM_BASE", "https://agoreum.xyz")
UA = {"User-Agent": "agoreum-surface-check/1.0"}

# Order-scoped GETs worth exercising rather than merely counting. A 404 is a
# legitimate answer for several of them; a 5xx never is.
EXERCISE = [
    "/api/v1/orders/{order_id}",
    "/api/v1/orders/{order_id}/settlement-options",
    "/api/v1/orders/{order_id}/reconcile",
    "/api/v1/orders/{order_id}/receipt",
    "/api/v1/orders/{order_id}/dispute",
]


def fetch(url: str, token: str | None = None) -> tuple[int, str]:
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def local_paths() -> set[str]:
    """The paths this repository would serve, from the app's own OpenAPI.

    Walking `app.routes` was the first attempt and it found exactly one route,
    because the routers are nested rather than flat, and it then announced with
    complete confidence that the deploy had not landed. Asking the application
    to describe itself the same way production does compares like with like, and
    cannot silently enumerate a fraction of the surface.
    """
    sys.path.insert(0, str(REPO / "apps" / "api"))
    from app.main import app  # noqa: PLC0415 - imported late, after sys.path

    paths = set(app.openapi().get("paths", {}))
    if len(paths) < 40:
        raise SystemExit(
            f"only {len(paths)} local paths were found, which is too few to be "
            "the whole API. Refusing to compare, because a comparison against a "
            "fraction of the surface reports a deploy failure that is really a "
            "bug in this script."
        )
    return paths


def sign_in() -> str | None:
    """Sign in as the operator, or return None and skip the exercising half.

    Skipping is reported loudly rather than silently, because a run that checked
    half of what it claims and says nothing is the failure this file exists for.
    """
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return None

    key = None
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DEPLOYER_PRIVATE_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        return None

    account = Account.from_key(key)
    payload = json.dumps(
        {"address": account.address.lower(), "chain_id": 84532}
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/nonce", data=payload,
        headers={**UA, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        challenge = json.load(response)
    signed = account.sign_message(encode_defunct(text=challenge["message"]))
    payload = json.dumps({
        "message": challenge["message"],
        "signature": signed.signature.hex(),
        "nonce": challenge["nonce"],
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/signin", data=payload,
        headers={**UA, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)["tokens"]["access_token"]


def main() -> int:
    status, body = fetch(f"{BASE}/api/v1/openapi.json")
    if status != 200:
        print(f"could not read the deployed contract: http {status}")
        return 1
    deployed = set(json.loads(body).get("paths", {}))
    here = local_paths()

    print(f"repository: {len(here)} GET routes, deployed: {len(deployed)} paths")

    missing = sorted(p for p in here if p not in deployed)
    # `/api/v1/openapi.json` serves the document and does not appear inside
    # it, so it is not a missing route.
    missing = [p for p in missing if not p.endswith("openapi.json")]
    if missing:
        print("\nin this repository and NOT deployed:")
        for path in missing:
            print(f"  {path}")
        print("\nThe deploy did not land. A job reporting success is not the same")
        print("as production serving the commit.")
        return 1
    print("every route in this repository is present in production")

    token = sign_in()
    if token is None:
        print("\nno operator key available, so nothing was exercised.")
        print("Half the question is unanswered: a route can be present and still")
        print("return 500 on every request, which is exactly what happened once.")
        return 1

    status, body = fetch(f"{BASE}/api/v1/orders", token)
    orders = json.loads(body) if status == 200 else []
    if not orders:
        print("\nno order to exercise the order-scoped routes against")
        return 1
    order_id = orders[0]["id"]
    print(f"\nexercising against order {orders[0]['reference']}")

    broken = []
    for template in EXERCISE:
        path = template.replace("{order_id}", order_id)
        status, body = fetch(f"{BASE}{path}", token)
        verdict = "ok" if status < 500 else "SERVER ERROR"
        print(f"  {status}  {verdict:12} {template}")
        if status >= 500:
            broken.append((template, status, body[:200]))

    if broken:
        print("\nPresent and broken, which enumerating paths would have called a pass:")
        for template, status, body in broken:
            print(f"  {template}: {status} {body}")
        return 1

    print("\nevery exercised route answered without a server error")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
