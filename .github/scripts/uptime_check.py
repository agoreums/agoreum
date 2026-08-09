"""Check the public site from outside the droplet.

The on-droplet monitor cannot report that the droplet is gone, because it goes
with it. A reboot drill confirmed this: the monitor sent nothing during the
outage and only reported a problem once it was back up. This runs on GitHub's
infrastructure instead, so it survives the thing it watches.

Checking the public URL is meaningful here, and that was verified rather than
assumed. Cloudflare's `always_online` is off and the HTML is not cached at the
edge, so when the origin went down during the drill the public URL returned
HTTP 521 rather than a stale page. If that ever changes, this check quietly
becomes a test of Cloudflare's cache instead of the site, so it also asserts the
API returns live JSON, which cannot be served from a static cache.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

import alerting

TIMEOUT = 20
WORKFLOW = "Uptime"

SITE = "https://agoreum.xyz/en"
API = "https://agoreum.xyz/api/v1/health/live"

# A single failed request is usually a blip, not an outage, and an alert channel
# that cries wolf gets muted. Three attempts spaced out must all fail.
ATTEMPTS = 3
GAP_SECONDS = 10


def probe(url: str, expect_json: bool) -> tuple[bool, str]:
    """One request. Returns (ok, detail) and never raises."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "agoreum-uptime-check",
            # Defence in depth against ever measuring a cache rather than the
            # origin, even if edge caching is turned on later.
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(4096)
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            if expect_json:
                payload = json.loads(body.decode())
                if payload.get("status") != "ok":
                    return False, f"status {payload.get('status')!r}"
            return True, "HTTP 200"
    except urllib.error.HTTPError as exc:
        # 521, 522 and 523 are Cloudflare saying it could not reach the origin,
        # which is exactly the case this check exists for.
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


def check() -> dict[str, str]:
    """Returns a mapping of failed target to reason. Empty means healthy."""
    failures: dict[str, str] = {}
    for name, url, expect_json in (("site", SITE, False), ("api", API, True)):
        for attempt in range(1, ATTEMPTS + 1):
            ok, detail = probe(url, expect_json)
            if ok:
                print(f"{name}: {detail} (attempt {attempt})")
                failures.pop(name, None)
                break
            print(f"{name}: {detail} (attempt {attempt} of {ATTEMPTS})")
            failures[name] = detail
            if attempt < ATTEMPTS:
                time.sleep(GAP_SECONDS)
    return failures


def main() -> int:
    if not alerting.credentials_present():
        print("FAIL: telegram credentials are not available to this workflow")
        return 1

    failures = check()

    if failures:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(failures.items()))
        alerting.telegram(
            "<b>Agoreum is unreachable from outside</b>\n"
            f"{detail}\n"
            f"checked {ATTEMPTS} times from GitHub, not from the droplet\n"
            f'<a href="{alerting.run_url()}">run</a>'
        )
        print(f"ALERTED: {detail}")
        # Non-zero so this run is recorded as a failure, which is what lets the
        # next healthy run know an all-clear is owed.
        return 1

    if alerting.previous_run_failed(WORKFLOW):
        alerting.telegram(
            "<b>Agoreum is reachable again</b>\n"
            f'site and API both answering\n<a href="{alerting.run_url()}">run</a>'
        )
        print("ALERTED: recovered")
    else:
        print("site and API healthy, nothing to report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
