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
WEB_ROOT = Path(__file__).resolve().parents[3] / "apps" / "web" / "src"

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


# The web app writes its paths in full, `/api/v1/...`, and appends query strings
# by interpolation: `/api/v1/api-keys${orgQuery(slug)}`. Normalised that becomes
# `/api/v1/api-keys{}`, which is the route plus a query rather than an extra
# path segment. Without this the check reports five confident false positives,
# which it did on the first run.
def _web_candidates() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for source in WEB_ROOT.rglob("*"):
        if source.suffix not in {".ts", ".tsx"} or not source.is_file():
            continue
        if any(part in {"node_modules", "tests"} for part in source.parts):
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        for raw in re.findall(r'["`](/api/v1/[^"`]*)["`]', text):
            # Query strings are not part of the route. They appear both
            # literally, `?window_days=${n}`, and via a helper appended whole,
            # so both forms are cut before comparing.
            found.setdefault(str(source.relative_to(WEB_ROOT)), set()).add(
                _normalise(raw.split("?")[0])
            )
    return found


def _served(path: str, api: set[str]) -> bool:
    if path in api:
        return True
    # A trailing interpolation is a query string helper, not a segment.
    if path.endswith("{}"):
        return path[:-2].rstrip("/") in api
    return False


def test_the_web_app_calls_endpoints_that_exist() -> None:
    """The surface users actually touch.

    The SDKs called a path that returned 404 for a year of commits without
    anything noticing. The same drift in here would break the product itself,
    so it is worth the same guard rather than the same discovery later.
    """
    api = _api_paths()
    candidates = _web_candidates()
    assert candidates, "no web API paths were found, so this test is checking nothing"

    missing = [
        f"{source}: {path}"
        for source, paths in sorted(candidates.items())
        for path in sorted(paths)
        if not _served(path, api)
    ]
    assert not missing, (
        "the web app calls an endpoint this API does not serve:\n  "
        + "\n  ".join(missing)
    )


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


# The public API documentation page hardcodes the scope catalogue as a literal
# array. The key-minting UI does not: it fetches `/api-keys/scopes` and renders
# whatever the API returns, so it cannot drift. The docs page can, and the drift
# would be the same shape as the endpoint path that was wrong in three published
# SDKs for a year: a duplicated contract with nothing comparing the copies.
#
# The failure is worse than cosmetic here. This page is what a developer reads
# to decide which scopes to request. A scope listed but not real means keys
# minted for something that will never work; a scope real but not listed means
# people granting more than they needed because the narrower option looked
# absent. Both are authorisation decisions made from a stale page.
DOCS_PAGE = WEB_ROOT / "app" / "[locale]" / "(public)" / "docs" / "api" / "page.tsx"

_SCOPE_ENTRY = re.compile(r'\[\s*"([a-z]+:[a-z]+)"\s*,\s*"([^"]+)"\s*\]')


def _documented_scopes() -> dict[str, str]:
    text = DOCS_PAGE.read_text(encoding="utf-8")
    block = text.split("const scopes", 1)[-1].split("];", 1)[0]
    return dict(_SCOPE_ENTRY.findall(block))


def test_the_documented_scopes_are_the_real_ones() -> None:
    from app.modules.apikeys.scopes import SCOPES

    documented = _documented_scopes()
    assert documented, (
        f"no scopes were parsed out of {DOCS_PAGE.name}, so this test is checking "
        "nothing. The page's `const scopes` array has probably been renamed or "
        "restructured."
    )

    assert set(documented) == set(SCOPES), (
        "the public API docs and the scope catalogue disagree about which scopes "
        f"exist.\n  documented but not real: {sorted(set(documented) - set(SCOPES))}"
        f"\n  real but undocumented: {sorted(set(SCOPES) - set(documented))}"
    )

    # Descriptions too, because a scope whose stated meaning has drifted is a
    # scope somebody grants for the wrong reason. `orders:write` covers acting
    # on disputes as well as placing orders, and a description that lost that
    # would understate what a leaked key can do.
    differing = [
        f"{scope}: docs say {documented[scope]!r}, catalogue says {SCOPES[scope]!r}"
        for scope in sorted(set(documented) & set(SCOPES))
        if documented[scope] != SCOPES[scope]
    ]
    assert not differing, "scope descriptions have drifted:\n  " + "\n  ".join(differing)
