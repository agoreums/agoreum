"""Report a CI outcome to the operator channel the monitor already uses.

Why this exists: the contracts job failed its formatting check for two commits
while every other job passed, and it was found by someone going to look rather
than by anything saying so. A red tick on a page nobody has open is not a
notification.

Two rules it follows:

- **Name what broke.** "CI failed" sends you to the run page to find out what.
  The message names the jobs, because that is the thing you actually need.
- **Send the all-clear too.** A failure alert with no recovery alert teaches
  people to ignore the channel, since a red message might be hours stale. This
  reports a success only when the previous run on main had failed, so a healthy
  main stays silent.
"""
from __future__ import annotations

import json
import os
import sys
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


def telegram(text: str) -> None:
    """Send one message. Raises on failure so the step surfaces a broken notifier."""
    if not BOT_TOKEN or not CHAT_ID:
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


def previous_run_failed() -> bool:
    """Did the run before this one, on main, fail?

    Used to decide whether a success is worth reporting. On any error this
    returns False, because the cost of guessing wrong is a missing all-clear,
    which is better than a spurious one.
    """
    if not GH_TOKEN or not REPO:
        return False
    url = (
        f"https://api.github.com/repos/{REPO}/actions/runs"
        "?branch=main&event=push&status=completed&per_page=10"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "agoreum-ci-notify",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            runs = json.load(resp).get("workflow_runs", [])
    except Exception as exc:
        print(f"could not read previous runs: {type(exc).__name__}: {exc}")
        return False

    for run in runs:
        # Skip this run and any other workflow that happens to share the branch.
        if str(run.get("id")) == RUN_ID or run.get("name") != "CI":
            continue
        return run.get("conclusion") == "failure"
    return False


def main() -> int:
    # Checked before deciding whether to send anything. On a green run the quiet
    # path sends nothing, so without this a workflow whose secrets had stopped
    # resolving would look identical to a healthy one, and the first anybody
    # would learn of it is a failure that never arrived. That is precisely the
    # class of silent gap this notifier exists to close, so it must not have one.
    if not BOT_TOKEN or not CHAT_ID:
        print("FAIL: telegram credentials are not available to this workflow")
        return 1
    print("telegram credentials present")

    needs = json.loads(os.environ.get("NEEDS", "{}"))
    failed = sorted(name for name, job in needs.items() if job.get("result") == "failure")
    run_url = f"{SERVER}/{REPO}/actions/runs/{RUN_ID}"
    short_sha = SHA[:7]

    if failed:
        jobs = ", ".join(failed)
        text = (
            f"<b>CI failed on main</b>\n"
            f"commit <code>{short_sha}</code>\n"
            f"failed: {jobs}\n"
            f'<a href="{run_url}">run</a>'
        )
    elif previous_run_failed():
        text = (
            f"<b>CI back to green on main</b>\n"
            f"commit <code>{short_sha}</code>\n"
            f'<a href="{run_url}">run</a>'
        )
    else:
        print("main is green and was already green, nothing to report")
        return 0

    telegram(text)
    print(f"reported: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
