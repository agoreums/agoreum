"""Every service in the compose file must be reachable by the deploy script.

This encodes a bug class that has cost this project real incidents twice, in
both of its forms.

**A service built from repository source that the deploy never rebuilds** keeps
running whatever image it started with. The deploy reports success and the code
is old.

**A service that mounts a file from the repository** has no image to rebuild, so
`up -d` sees nothing changed and leaves the old process running with whatever it
read at start. That one is worse, because the file on disk is new and the
behaviour is old. An added governance alert sat undeployed for hours while the
runbook claimed the event was watched, and a real settlement passed unannounced.

Both are invisible at deploy time, which is why they need a check rather than
care. Run directly, or in CI:

    python scripts/check_deploy_coverage.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / "scripts" / "deploy.sh"


def build_targets(deploy: str) -> set[str]:
    """Service names passed to any `compose build` line in the deploy script."""
    names: set[str] = set()
    for line in re.findall(r"^\s*\$COMPOSE build (.+)$", deploy, re.M):
        names |= {n for n in line.split() if not n.startswith("-")}
    return names


def mounts_repo_files(service: dict) -> bool:
    """Whether the service binds a path from this repository into the container.

    A named volume does not count: it holds state rather than code, so it cannot
    go stale against the repository.
    """
    for volume in service.get("volumes") or []:
        source = volume.split(":")[0] if isinstance(volume, str) else volume.get("source", "")
        if source.startswith((".", "/")) or "${PWD}" in source:
            return True
    return False


def main() -> int:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    deploy = DEPLOY.read_text(encoding="utf-8")
    services = compose.get("services") or {}
    built = build_targets(deploy)

    problems: list[str] = []
    for name, service in services.items():
        service = service or {}
        if "build" in service and name not in built:
            problems.append(
                f"{name} is built from repository source but no `$COMPOSE build` "
                f"line in scripts/deploy.sh names it, so a deploy would keep "
                f"running the old image"
            )
        if mounts_repo_files(service) and not re.search(rf"\b{re.escape(name)}\b", deploy):
            problems.append(
                f"{name} mounts a file from the repository but is never named in "
                f"scripts/deploy.sh, so changing that file would not reach the "
                f"running process"
            )

    print(f"{len(services)} services in {COMPOSE.name}")
    for name, service in sorted(services.items()):
        service = service or {}
        kind = []
        if "build" in service:
            kind.append("built here")
        if mounts_repo_files(service):
            kind.append("mounts repo files")
        print(f"  {name:24} {', '.join(kind) or 'stock image, nothing to redeploy'}")

    if problems:
        print()
        for p in problems:
            print(f"::error::{p}")
        return 1

    print("\nevery service is reachable by the deploy script")
    return 0


if __name__ == "__main__":
    sys.exit(main())
