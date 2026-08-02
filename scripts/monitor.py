#!/usr/bin/env python3
"""Uptime and error monitor for the Agoreum production stack.

Runs as its own container. Every interval it checks three things and alerts to
Telegram when the state changes, so an operator hears about a problem once, when
it starts and again when it clears, rather than every minute in between:

  1. The public site, end to end through Cloudflare and nginx (uptime).
  2. The API's own dependency health: database, Redis, chain (error conditions).
  3. Indexer freshness: is the chain indexer keeping up, or has it stalled while
     buyers' paid orders quietly go unfunded.

Standard library only, so it needs no build and no extra image. It never sends a
single byte to Telegram until a chat id is configured, so it is safe to run
before that is wired.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

INTERVAL = int(os.environ.get("MONITOR_INTERVAL", "60"))
SITE_URL = os.environ.get("MONITOR_SITE_URL", "https://agoreum.xyz/en")
API_BASE = os.environ.get("MONITOR_API_BASE", "http://api:8000/api/v1")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# A real outage must fail this many checks in a row before it pages. A deploy
# recreates containers for a few seconds, which briefly 502s; without this every
# deploy would alert. At a 60s interval, two failures is a ~2 minute real outage.
FAIL_THRESHOLD = int(os.environ.get("MONITOR_FAIL_THRESHOLD", "2"))
# A daily "still healthy" heartbeat, so silence is never mistaken for a dead monitor.
HEARTBEAT_SECONDS = int(os.environ.get("MONITOR_HEARTBEAT_SECONDS", "86400"))

TIMEOUT = 12


def _get(url: str) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "agoreum-monitor"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[alert suppressed, no chat id] {text}", flush=True)
        return
    data = urllib.parse.urlencode(
        {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    ).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data, timeout=TIMEOUT
        )
    except Exception as exc:  # pragma: no cover
        print(f"[telegram send failed] {type(exc).__name__}: {exc}", flush=True)


def check() -> tuple[bool, list[str]]:
    """Return (healthy, list of problem descriptions)."""
    problems: list[str] = []

    code, _ = _get(SITE_URL)
    if code != 200:
        problems.append(f"site: agoreum.xyz returned HTTP {code or 'no response'}")

    code, body = _get(f"{API_BASE}/health/ready")
    if body is None:
        problems.append("api: /health/ready unreachable")
    else:
        for name, comp in (body.get("components") or {}).items():
            if comp.get("status") == "down":
                problems.append(f"api: {name} is down ({comp.get('error', 'unknown')})")

    code, body = _get(f"{API_BASE}/health/indexer")
    if body is not None:
        idx = body.get("indexer", {})
        if idx.get("status") == "down":
            problems.append(f"indexer: stalled ({idx.get('lag_blocks', '?')} blocks behind head)")

    code, body = _get(f"{API_BASE}/health/workers")
    if body is not None:
        sub = body.get("subscription_indexer", {})
        if sub.get("status") == "down":
            problems.append(
                f"subscription indexer: stalled ({sub.get('lag_blocks', '?')} blocks behind head)"
            )
        hook = body.get("webhooks_worker", {})
        if hook.get("status") == "down":
            problems.append(
                f"webhooks worker: not delivering ({hook.get('heartbeat_age_seconds', '?')}s since last heartbeat)"
            )

    return (len(problems) == 0), problems


def main() -> None:
    print(
        f"monitor up: interval={INTERVAL}s site={SITE_URL} api={API_BASE} "
        f"telegram={'configured' if (BOT_TOKEN and CHAT_ID) else 'NOT configured'}",
        flush=True,
    )
    consecutive_fail = 0
    alerted = False  # whether a PROBLEM alert is currently outstanding
    announced_start = False
    last_heartbeat = time.time()

    while True:
        healthy, problems = check()

        if healthy:
            if alerted:
                telegram("RECOVERED: Agoreum is passing all checks again.")
                alerted = False
            elif not announced_start:
                telegram("Agoreum monitor started: all checks passing.")
            consecutive_fail = 0
            announced_start = True
        else:
            consecutive_fail += 1
            if consecutive_fail >= FAIL_THRESHOLD and not alerted:
                telegram(
                    f"PROBLEM: Agoreum check failed {consecutive_fail} times in a row:\n- "
                    + "\n- ".join(problems)
                )
                alerted = True
                announced_start = True

        if not alerted and time.time() - last_heartbeat > HEARTBEAT_SECONDS:
            telegram("Heartbeat: Agoreum is healthy (daily check-in).")
            last_heartbeat = time.time()

        state = "healthy" if healthy else f"PROBLEMS (x{consecutive_fail}): " + "; ".join(problems)
        print(f"[{time.strftime('%H:%M:%S')}] {state}", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
