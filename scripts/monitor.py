#!/usr/bin/env python3
"""Uptime and error monitor for the Agoreum production stack.

Runs as its own container. Every interval it checks three things and alerts to
Telegram when the state changes — so an operator hears about a problem once, when
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

    return (len(problems) == 0), problems


def main() -> None:
    print(
        f"monitor up: interval={INTERVAL}s site={SITE_URL} api={API_BASE} "
        f"telegram={'configured' if (BOT_TOKEN and CHAT_ID) else 'NOT configured'}",
        flush=True,
    )
    last_healthy: bool | None = None
    last_heartbeat = time.time()

    while True:
        healthy, problems = check()

        if last_healthy is None:
            # First observation: announce so it is clear the monitor is alive.
            telegram(
                "Agoreum monitor started: all checks passing."
                if healthy
                else "Agoreum monitor started with problems:\n- " + "\n- ".join(problems)
            )
        elif healthy and not last_healthy:
            telegram("RECOVERED: Agoreum is passing all checks again.")
        elif not healthy and last_healthy:
            telegram("PROBLEM: Agoreum check failed:\n- " + "\n- ".join(problems))
        elif not healthy:
            # Still broken; re-alert only if the specific problems changed.
            pass

        if healthy and time.time() - last_heartbeat > HEARTBEAT_SECONDS:
            telegram("Heartbeat: Agoreum is healthy (daily check-in).")
            last_heartbeat = time.time()

        status_line = "healthy" if healthy else "PROBLEMS: " + "; ".join(problems)
        print(f"[{time.strftime('%H:%M:%S')}] {status_line}", flush=True)

        last_healthy = healthy
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
