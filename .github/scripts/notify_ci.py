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

import alerting

WORKFLOW = "CI"


def main() -> int:
    if not alerting.credentials_present():
        print("FAIL: telegram credentials are not available to this workflow")
        return 1
    print("telegram credentials present")

    needs = json.loads(os.environ.get("NEEDS", "{}"))
    failed = sorted(name for name, job in needs.items() if job.get("result") == "failure")
    short_sha = alerting.SHA[:7]

    if failed:
        text = (
            "<b>CI failed on main</b>\n"
            f"commit <code>{short_sha}</code>\n"
            f"failed: {', '.join(failed)}\n"
            f'<a href="{alerting.run_url()}">run</a>'
        )
    elif alerting.previous_run_failed(WORKFLOW, event="push"):
        text = (
            "<b>CI back to green on main</b>\n"
            f"commit <code>{short_sha}</code>\n"
            f'<a href="{alerting.run_url()}">run</a>'
        )
    else:
        print("main is green and was already green, nothing to report")
        return 0

    alerting.telegram(text)
    print(f"reported: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
