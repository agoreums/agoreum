#!/usr/bin/env python3
"""The running record must move when the code moves.

`docs/operating-model.md` carries a `## Running record` section written for a
session starting cold: what is true now, what each strand did last, what is
open, and what was decided. It is only worth reading if it is true.

Keeping it true was an instruction for weeks, and instructions of that shape are
exactly what this project has spent a month watching rot. The SDK version
constants carried a comment saying they were kept in sync with package.json and
nothing kept them in sync. The public docs page duplicated the scope catalogue
and nothing compared them. Two auditor-facing documents quoted a test count
maintained by hand and both were wrong by the time anybody read them. In every
case the rule was written down, believed, and unenforced.

So this is the check under the rule. If a commit changes code and the record's
`Last updated` date is older than that commit, the build fails and names what
landed without the record moving.

**Why the date rather than a content diff.** A content check would be satisfied
by touching the file, which is worse than no check because it looks like one.
The date is a claim the author has to make deliberately, and making it while
knowing this runs is the point: the cost is not the edit, it is being unable to
say the record is current without having looked.

Documentation-only commits are exempt, since a record describing itself is not
what this is protecting.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECORD = REPO / "docs" / "operating-model.md"

# `**Last updated:** 2026-08-16, after `8dab8c3`.` The trailing commit is
# optional so the line stays easy to write by hand under time pressure, which is
# when it is most likely to be skipped.
LAST_UPDATED = re.compile(r"^\*\*Last updated:\*\*\s*(\d{4})-(\d{2})-(\d{2})", re.MULTILINE)

# Paths whose change does not require the record to move. Deliberately narrow:
# anything that alters behaviour, configuration or infrastructure counts as work
# somebody arriving cold would need to know about.
EXEMPT_PREFIXES = (
    "docs/",
    "README.md",
    "LICENSE",
)
EXEMPT_SUFFIXES = (".md",)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def record_date() -> date:
    """The date the running record claims for itself.

    Written the obvious way first, with `search` over the whole file, and that
    version had a real defect caught by mutating the document rather than the
    code. The file carried two `Last updated` lines, one under the running
    record and an older one under what is now the roadmap section. Deleting the
    record's line left the check reading the other section's date and reporting
    the record current while nothing maintained it.

    That is the failure this whole script exists to prevent, reproduced inside
    the script on the day it was written, which is a fair measure of how easily
    it happens. So the count is asserted: more than one such line is refused as
    ambiguous rather than resolved by picking one, because picking one is what
    went wrong.
    """
    text = RECORD.read_text(encoding="utf-8")
    matches = LAST_UPDATED.findall(text)

    if not matches:
        raise SystemExit(
            f"{RECORD.relative_to(REPO)} has no '**Last updated:** YYYY-MM-DD' "
            "line, so there is no way to tell whether the running record is "
            "current. Add one directly under '## Running record'."
        )
    if len(matches) > 1:
        raise SystemExit(
            f"{RECORD.relative_to(REPO)} carries {len(matches)} 'Last updated' "
            "lines. Exactly one section may claim to be the running record, "
            "because a check that picks between them silently reads the wrong "
            "one, which is precisely how this script was first wrong."
        )

    year, month, day = matches[0]
    return date(int(year), int(month), int(day))


def is_code(path: str) -> bool:
    if path.startswith(EXEMPT_PREFIXES):
        return False
    return not path.endswith(EXEMPT_SUFFIXES)


def commits_since(cutoff: date) -> list[tuple[str, date, str]]:
    """Commits after the cutoff date that touched something other than prose."""
    raw = _git(
        "log",
        f"--since={cutoff.isoformat()}",
        "--date=short",
        "--pretty=format:%h\x1f%ad\x1f%s",
        "--name-only",
    )
    if not raw:
        return []

    found: list[tuple[str, date, str]] = []
    sha = when = subject = None
    files: list[str] = []

    def flush() -> None:
        if sha and any(is_code(f) for f in files):
            found.append((sha, when, subject))

    for line in raw.splitlines():
        if "\x1f" in line:
            flush()
            sha, raw_date, subject = line.split("\x1f", 2)
            when = date.fromisoformat(raw_date)
            files = []
        elif line.strip():
            files.append(line.strip())
    flush()

    # `--since` is inclusive of the whole cutoff day, which is what we want: a
    # record updated today covers work committed today.
    return [c for c in found if c[1] > cutoff]


def main() -> int:
    if not RECORD.exists():
        print(f"missing {RECORD.relative_to(REPO)}", file=sys.stderr)
        return 1

    cutoff = record_date()
    stale = commits_since(cutoff)

    if not stale:
        print(f"running record is current, last updated {cutoff.isoformat()}")
        return 0

    print(
        f"the running record in {RECORD.relative_to(REPO)} says it was last "
        f"updated {cutoff.isoformat()}, but these commits changed code after "
        "that and did not move it:",
        file=sys.stderr,
    )
    for sha, when, subject in stale:
        print(f"  {sha}  {when.isoformat()}  {subject}", file=sys.stderr)
    print(
        "\nA session starting cold reads that section and acts on it. Update "
        "'## Running record' with what changed, then set the 'Last updated' "
        "line to today. Bumping the date without reading the section is the one "
        "way to make this check worse than useless.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
