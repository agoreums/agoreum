"""Every endpoint the official SDKs call must exist in this API.

All three SDKs asked for `/orders/{id}/payment` while the API has always served
`/orders/{id}/payment-instructions`. That is the call a buyer uses to get the
calldata their wallet needs to fund an escrow, so the single most important
operation in a commerce SDK returned 404 in the published Python, TypeScript and
Go packages.

Three CI jobs passed throughout, because the SDK suites exercise their clients
against mock servers. A mock answers whatever path the client asks for, so those
tests assert the implementation rather than the contract, and would have kept
passing however wrong the path became.

This compares the SDK sources against the API's own schema, which is the only
thing that can disagree with them. It is deliberately here rather than in the
SDK suites: this is the side that knows what the routes are.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SDK_ROOT = Path(__file__).resolve().parents[3] / "sdks"

# Quoted or backticked strings that look like an API path. Interpolation is
# normalised to a placeholder so `/orders/${id}/x` and `/orders/{id}/x` compare
# the same way across three languages.
_PATH = re.compile(r"""["'`](/[a-zA-Z0-9_{}$()./-]*)["'`]""")
_PARAM = re.compile(r"\$?\{[^}]*\}|\$\([^)]*\)")

# Go builds paths by concatenation: `"/orders/" + escape(id) + "/payment"`. Left
# alone, the extractor above sees two unrelated literals, `/orders/` which is a
# real route and `/payment` which does not start with a known resource, so it
# matches neither and the check passes on a broken path.
#
# That is not hypothetical. The first version of this file did exactly that, and
# reintroducing the original defect in the Go SDK did not fail it. Joining the
# pieces first is what makes this cover all three languages rather than two.
_CONCAT = re.compile(r"""["'`]\s*\+\s*[^"'`+]+?\s*\+\s*["'`]""")


def _join_concatenations(text: str) -> str:
    """Collapse `"a" + expr + "b"` into a single `"a{}b"` literal."""
    previous = None
    while previous != text:
        previous = text
        text = _CONCAT.sub("{}", text)
    return text


def _normalise(path: str) -> str:
    return _PARAM.sub("{}", path).rstrip("/") or "/"


def _api_paths() -> set[str]:
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
    return {_normalise(p) for p in spec.get("paths", {})}


def _sdk_candidates() -> dict[str, set[str]]:
    """Paths each SDK appears to call, keyed by source file.

    Only strings whose first segment is a real API resource are considered. An
    unrelated literal such as a docs link therefore cannot fail this, while a
    path that drifts within a resource, which is the failure that actually
    happened, still does.
    """
    api = _api_paths()
    prefix = "/api/v1"
    resources = {p[len(prefix):].split("/")[1] for p in api if p.startswith(prefix + "/")}

    found: dict[str, set[str]] = {}
    for source in SDK_ROOT.rglob("*"):
        if source.suffix not in {".py", ".ts", ".go"} or not source.is_file():
            continue
        if any(part in {"node_modules", "dist", "__pycache__", "test", "tests"}
               for part in source.parts):
            continue
        text = _join_concatenations(source.read_text(encoding="utf-8", errors="ignore"))
        for raw in _PATH.findall(text):
            candidate = _normalise(raw)
            segments = [s for s in candidate.split("/") if s]
            if segments and segments[0] in resources:
                found.setdefault(str(source.relative_to(SDK_ROOT)), set()).add(candidate)
    return found


def test_the_sdks_reference_endpoints_that_exist() -> None:
    api = _api_paths()
    candidates = _sdk_candidates()
    assert candidates, "no SDK paths were found, so this test is checking nothing"

    missing: list[str] = []
    for source, paths in sorted(candidates.items()):
        for path in sorted(paths):
            if "/api/v1" + path not in api:
                missing.append(f"{source}: {path}")

    assert not missing, (
        "SDK calls an endpoint this API does not serve:\n  "
        + "\n  ".join(missing)
    )


@pytest.mark.parametrize(
    "path",
    ["/orders/{}/payment-instructions", "/marketplace/services", "/agents/{}", "/me"],
)
def test_the_paths_this_check_relies_on_are_real(path: str) -> None:
    """Guards the guard.

    If the schema ever stopped exposing these, `_sdk_candidates` would find no
    known resources, silently match nothing, and the test above would pass while
    checking an empty set.
    """
    assert "/api/v1" + path in _api_paths()
