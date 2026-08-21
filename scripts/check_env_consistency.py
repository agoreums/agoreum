#!/usr/bin/env python3
"""A credential defined twice is a credential that will be rotated once.

On 2026-08-21 the Alchemy key was rotated and `ALCHEMY_API_KEY` was updated.
`ALCHEMY_BASE_URL_MAINNET` and `ALCHEMY_BASE_URL_SEPOLIA` embed the same key in
a URL and were not, so they still carried the revoked one. Production kept
serving, every health endpoint reported `status: ok`, and the indexer 401ed on
every poll until somebody looked. Orders would have stopped being funded or
settled while nothing said so.

That is the shape this repository keeps finding, arriving through a new door:
the failure was not that anybody was careless, it was that the file allowed the
same secret to be written in three places and nothing compared them. The
project's own rule already says two sources of truth for a secret is zero. This
is the check under that rule.

Compares every place a credential appears and requires them to agree. A
deployment carrying only the URL and not the standalone key passes, because one
occurrence cannot disagree with itself; production is configured exactly that
way, and the first version of this check failed its deploy for it.

Run against any env file. Exits non-zero and names the disagreement.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# name of the standalone variable -> variables embedding it in a URL.
EMBEDDED_SECRETS: dict[str, tuple[str, ...]] = {
    "ALCHEMY_API_KEY": ("ALCHEMY_BASE_URL_MAINNET", "ALCHEMY_BASE_URL_SEPOLIA"),
}

# Anything matching this inside a URL is a credential segment worth comparing.
URL_SECRET = re.compile(r"/v2/([A-Za-z0-9_-]{8,})")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".env"
    if not path.exists():
        print(f"no env file at {path}", file=sys.stderr)
        return 1

    values = read_env(path)
    problems: list[str] = []
    present = 0

    for standalone, url_vars in EMBEDDED_SECRETS.items():
        # Every place this credential appears, and what it says there.
        occurrences: dict[str, str] = {}

        secret = values.get(standalone)
        if secret:
            present += 1
            occurrences[standalone] = secret

        for url_var in url_vars:
            url = values.get(url_var)
            if not url:
                continue
            present += 1
            found = URL_SECRET.search(url)
            if not found:
                problems.append(
                    f"{url_var} carries no recognisable key segment, so it cannot "
                    f"be compared against the others"
                )
            else:
                occurrences[url_var] = found.group(1)

        distinct = set(occurrences.values())
        if len(distinct) > 1:
            names = ", ".join(sorted(occurrences))
            problems.append(
                f"{names} do not all carry the same {standalone}. Rotating one "
                "and not the others is what took the indexer down on 2026-08-21, "
                "silently, while every health check reported ok."
            )

    # A deployment may legitimately carry only the URL and not the standalone
    # key, which is how production is configured, and one occurrence cannot
    # disagree with itself. That is a pass, not a gap to complain about.
    #
    # What must not pass is finding nothing at all, which means the variables
    # were renamed and this check is no longer looking at what it thinks it is.
    # The first version of this conflated the two and failed the deploy on a
    # perfectly good production environment.
    if present == 0:
        print(
            f"{path.name}: none of the variables this checks are present at all "
            f"({', '.join(sorted(EMBEDDED_SECRETS))} and the URLs embedding them). "
            "Either they were renamed or this check is no longer looking at what "
            "it thinks it is.",
            file=sys.stderr,
        )
        return 1

    if problems:
        print(f"{path.name}: credentials disagree with themselves:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"{path.name}: {present} credential occurrence(s) checked, all agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
