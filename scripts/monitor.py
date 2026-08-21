#!/usr/bin/env python3
"""Uptime and error monitor for the Agoreum production stack.

Runs as its own container. Every interval it checks three things and alerts to
Telegram when the state changes, so an operator hears about a problem once, when
it starts and again when it clears, rather than every minute in between:

  1. The public site, end to end through Cloudflare and nginx (uptime).
  2. The API's own dependency health: database, Redis, chain (error conditions).
  3. Indexer freshness: is the chain indexer keeping up, or has it stalled while
     buyers' paid orders quietly go unfunded.
  4. Governance events on the escrow contract: a fee change, a fee recipient
     change, or any role being granted or revoked.

The fourth is a different kind of check from the first three. Those ask whether
the system is up; this one asks whether someone changed who controls it. A
compromised admin key cannot drain principal, but it can raise the fee to the
10% ceiling and redirect the fee stream of escrows that are already funded, and
without this the first sign of that would be a user complaint. Every one of these
events is rare and deliberate in normal operation, so alerting on all of them
produces near-zero noise and catches the case that matters.

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
# Governance watch. Needs an RPC endpoint and the deployed escrow address; with
# either missing the check is skipped rather than failing, so the monitor still
# runs everywhere else it is useful.
RPC_URL = os.environ.get("MONITOR_RPC_URL", "")
ESCROW_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS", "")
# How far back to look on the first pass, so a restart does not replay history.
GOV_LOOKBACK_BLOCKS = int(os.environ.get("MONITOR_GOV_LOOKBACK_BLOCKS", "500"))

# keccak256 of each event signature, computed from the declarations in
# contracts/src and verified against them, not written from memory. Precomputed
# so the monitor keeps its standard-library-only promise, which is the trade:
# these must be regenerated if an event signature ever changes. A wrong topic
# here fails silently, the alert simply never fires, which is worse than having
# no alert at all because it looks like coverage.
GOVERNANCE_TOPICS = {
    # FeeConfigUpdated(uint256,address)
    "0xe125ae54d7ba2b06e6f44852861516acb2dd2692cf41fb127fa03252f15b334e":
        "fee config changed",
    # TreasuryUpdated(address), on the subscriptions contract
    "0x7dae230f18360d76a040c81f050aa14eb9d6dc7901b20fc5d855e2a20fe814d1":
        "TREASURY REDIRECTED",
    # EscrowSettled(bytes32,uint256,uint256,uint256,address)
    # Every dispute settlement, not only an unexpected one. Settlements are rare
    # and each is a person's money being split by a decision, so the operator
    # should learn about all of them; a settlement nobody expected is the exact
    # shape of a compromised arbiter key.
    "0xd8d0a3f861feaff7f935ea1516957d14f952ec2fb9623e97562dfe939ea3fd5e":
        "DISPUTE SETTLED",
    # RoleGranted(bytes32,address,address)
    "0x2f8788117e7eff1d82e926ec794901d17c78024a50270940304540a733656f0d":
        "ROLE GRANTED",
    # RoleRevoked(bytes32,address,address)
    "0xf6391f5c32d9c69d2a47ea670b442974b53935d1edc7fd64eb21e047a839171b":
        "role revoked",
    # Paused(address)
    "0x62e78cea01bee320cd4e420270b5ea74000d11b0c9f74754ebdbfc544b05a258":
        "contract PAUSED",
    # Unpaused(address)
    "0x5db9ee0a495bf2e6ff9c91a7834c1ba4fdd244a5e8aa4e537bd38aeae4b073aa":
        "contract unpaused",
}
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


def _rpc(method: str, params: list) -> dict | None:
    """One JSON-RPC call. Returns None on any failure rather than raising, since a
    flaky RPC must never take the uptime monitor down with it."""
    if not RPC_URL:
        return None
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        RPC_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"[rpc failed] {method}: {type(exc).__name__}: {exc}", flush=True)
        return None


def governance_events(from_block: int | None) -> tuple[list[str], int | None]:
    """Governance events on the escrow since `from_block`.

    Returns the alerts and the block to resume from. Deliberately separate from
    `check()`: those are state checks that alert on a transition and clear when
    healthy, whereas these are one-off facts that must be reported exactly once
    and never "clear". Folding them into the same up/down machinery would either
    repeat them every interval or lose them.
    """
    if not RPC_URL or not ESCROW_ADDRESS:
        return [], None

    head_resp = _rpc("eth_blockNumber", [])
    if not head_resp or "result" not in head_resp:
        return [], from_block
    head = int(head_resp["result"], 16)

    # First pass after a restart: look back a bounded window rather than replaying
    # the whole chain, so a restart cannot spam every historical role grant.
    start = from_block if from_block is not None else max(0, head - GOV_LOOKBACK_BLOCKS)
    if start > head:
        return [], head + 1

    logs_resp = _rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start),
            "toBlock": hex(head),
            "address": ESCROW_ADDRESS,
            "topics": [list(GOVERNANCE_TOPICS.keys())],
        }],
    )
    if not logs_resp or "result" not in logs_resp:
        # Do not advance the cursor on failure, or the missed range is lost.
        return [], start

    alerts = []
    for log in logs_resp["result"]:
        topics = log.get("topics") or []
        if not topics:
            continue
        label = GOVERNANCE_TOPICS.get(topics[0].lower(), "unknown governance event")
        block = int(log.get("blockNumber", "0x0"), 16)
        tx = log.get("transactionHash", "?")
        alerts.append(f"governance: {label} on the escrow at block {block} (tx {tx})")

    return alerts, head + 1


# Half an hour. Generous, because this is watching for a clock that is wrong by
# days rather than one that is drifting by seconds, and an alert that fires on
# ordinary NTP correction is an alert people learn to ignore.
MAX_CLOCK_SKEW_SECONDS = 1800


def _clock_skew_seconds() -> float | None:
    """This host's clock minus the network's, in seconds, or None if unknown.

    Read from the Date header of the site the monitor already polls. Cloudflare
    and nginx both stamp it, both take it from a synchronised clock, and it
    arrives on a request this function does not have to make.

    Returns None rather than zero when it cannot tell, so an unreadable header
    reports "unknown" instead of "fine", which is the difference between a check
    that abstains and one that lies.
    """
    import email.utils
    import urllib.request

    try:
        with urllib.request.urlopen(SITE_URL, timeout=10) as response:
            stamp = response.headers.get("Date")
    except urllib.error.HTTPError as exc:
        # An error page still carries a Date header, and a clock check has no
        # reason to care whether the site returned 200 or 502.
        stamp = exc.headers.get("Date") if exc.headers else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not stamp:
        return None
    try:
        network = email.utils.parsedate_to_datetime(stamp).timestamp()
    except (TypeError, ValueError):
        return None
    return time.time() - network


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

    # Clock skew.
    #
    # This droplet's clock was three days behind real time during the session of
    # 2026-08-21, corrected by NTP part way through, and nothing anywhere would
    # have said so. It was noticed only because a backup filename disagreed with
    # a commit date.
    #
    # It matters more here than on most servers. Every deadline this product
    # enforces is a timestamp comparison: the funding window that freezes a
    # price, the delivery window, the auto-release deadline after which anybody
    # may release an escrow, and the dispute window a buyer relies on. A clock
    # that jumps forward expires all of them at once, and a permissionless
    # auto-release firing early pays a provider before the buyer's window to
    # dispute has run. That is the exact property the deadline invariant in the
    # contract suite exists to protect, defeated from outside the contract.
    #
    # Compared against the Date header of a response the monitor already makes,
    # so this costs no extra request and needs no time service of its own.
    if body is not None or code:
        skew = _clock_skew_seconds()
        if skew is not None and abs(skew) > MAX_CLOCK_SKEW_SECONDS:
            problems.append(
                f"clock: this host is {skew:+.0f}s from the network, which is "
                f"past the {MAX_CLOCK_SKEW_SECONDS}s tolerance. Every funding, "
                "delivery, auto-release and dispute deadline is a timestamp "
                "comparison against this clock."
            )

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
        # Added 2026-08-15. The endpoint reported two workers and production ran
        # four, and the missing one sends sign-in alerts and verification links.
        # Its silence is the hardest to notice from outside, because nobody
        # reports mail they were never expecting.
        mail = body.get("emails_worker", {})
        if mail.get("status") == "down":
            problems.append(
                f"emails worker: not delivering ({mail.get('heartbeat_age_seconds', '?')}s since last heartbeat)"
            )

    return (len(problems) == 0), problems


def main() -> None:
    print(
        f"monitor up: interval={INTERVAL}s site={SITE_URL} api={API_BASE} "
        f"telegram={'configured' if (BOT_TOKEN and CHAT_ID) else 'NOT configured'} "
        f"governance={'watching ' + ESCROW_ADDRESS if (RPC_URL and ESCROW_ADDRESS) else 'OFF'}",
        flush=True,
    )
    consecutive_fail = 0
    alerted = False  # whether a PROBLEM alert is currently outstanding
    announced_start = False
    last_heartbeat = time.time()
    gov_cursor: int | None = None

    while True:
        healthy, problems = check()

        # Reported separately from the health checks and independently of the
        # failure threshold. A role grant is not an outage to be debounced, it is
        # a fact that happened once and must be said once, immediately.
        gov_alerts, gov_cursor = governance_events(gov_cursor)
        for alert in gov_alerts:
            telegram(f"GOVERNANCE: {alert}")
            print(f"[governance] {alert}", flush=True)

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
