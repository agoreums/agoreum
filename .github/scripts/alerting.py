"""Shared alerting for workflows that need to reach an operator.

Both the CI notifier and the external uptime check send to the same Telegram
channel the on-droplet monitor uses, so an operator has one place to look rather
than three.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

TIMEOUT = 15

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
SHA = os.environ.get("GITHUB_SHA", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")


def credentials_present() -> bool:
    """Whether this workflow can actually send.

    Checked before deciding whether there is anything to say. A quiet path that
    returns early would otherwise make a workflow whose secrets stopped
    resolving look identical to a healthy one, and the first anybody would learn
    of it is an alert that never arrived.
    """
    return bool(BOT_TOKEN and CHAT_ID)


def telegram(text: str) -> None:
    """Send one message. Raises on failure, so a broken notifier is visible."""
    if not credentials_present():
        raise RuntimeError("no telegram credentials available to the workflow")
    data = urllib.parse.urlencode(
        {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode()
    urllib.request.urlopen(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data, timeout=TIMEOUT
    )


def run_url() -> str:
    return f"{SERVER}/{REPO}/actions/runs/{RUN_ID}"


def previous_run_failed(workflow_name: str, *, branch: str = "main",
                        event: str | None = None) -> bool:
    """Did the run before this one, for this workflow, fail?

    Used to decide whether a success is worth reporting, so a healthy system
    stays silent. On any error this returns False: a missing all-clear is a
    better failure than a spurious one.
    """
    if not GH_TOKEN or not REPO:
        return False
    query = f"branch={branch}&status=completed&per_page=15"
    if event:
        query += f"&event={event}"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/runs?{query}",
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "agoreum-ops",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            runs = json.load(resp).get("workflow_runs", [])
    except Exception as exc:
        print(f"could not read previous runs: {type(exc).__name__}: {exc}")
        return False

    for run in runs:
        if str(run.get("id")) == RUN_ID or run.get("name") != workflow_name:
            continue
        return run.get("conclusion") == "failure"
    return False
