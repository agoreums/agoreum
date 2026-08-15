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


# --- What the SDKs can actually do -------------------------------------------
#
# Enforcing the three write scopes made 18 endpoints reachable by API key, and
# the published SDKs exposed exactly one of them, `place`. A developer who read
# the scope catalogue, saw "Create, update, and change the status of your
# agents", granted `agents:write` and reached for the client found nothing
# there. Fifteen are covered now.
#
# The gap itself was a judgement call about SDK scope. Its invisibility was not.
# Nothing in this repository stated which write endpoints the clients cover, so
# the answer was only discoverable by reading three SDKs and comparing them to a
# router by hand. This table states it, and the test below makes the app and the
# table agree, so a new write endpoint cannot be added without someone deciding
# what the SDKs do about it.
#
# Value is the canonical method name the clients expose, or None with the reason
# it is deliberately absent.
SDK_WRITE_COVERAGE: dict[tuple[str, str], str | None] = {
    # Orders: the buyer and seller lifecycle.
    ("POST", "/orders"): "place",
    ("POST", "/orders/{order_id}/start"): "start",
    ("POST", "/orders/{order_id}/deliver"): "deliver",
    ("POST", "/orders/{order_id}/dispute-intent"): "raise_dispute",
    ("POST", "/orders/{order_id}/dispute-statements"): "submit_dispute_statement",
    # Arbiter only. Settling a dispute requires ARBITER_ROLE on chain, which an
    # ordinary integrator's key cannot have, so a client method would fail for
    # everyone who could call it.
    ("POST", "/orders/{order_id}/dispute-decision"): None,
    # Agents: registering and running an identity.
    ("POST", "/agents"): "create",
    ("PATCH", "/agents/{slug}"): "update",
    ("POST", "/agents/{slug}/publish"): "publish",
    ("POST", "/agents/{slug}/pause"): "pause",
    ("PUT", "/agents/{slug}/payout-wallet"): "set_payout_wallet",
    # Identity verification. Both require serving a challenge from a domain or a
    # GitHub account, which is a human step in the middle, so the API call is
    # only the last third of the flow.
    ("POST", "/agents/{slug}/domain-challenges/{challenge_id}/verify"): None,
    ("POST", "/agents/{slug}/github-challenges/{challenge_id}/verify"): None,
    # Services: publishing what an agent sells.
    ("POST", "/agents/{agent_slug}/services"): "create",
    ("PATCH", "/agents/{agent_slug}/services/{service_slug}"): "update",
    ("POST", "/agents/{agent_slug}/services/{service_slug}/publish"): "publish",
    ("POST", "/agents/{agent_slug}/services/{service_slug}/availability"): "set_availability",
    ("DELETE", "/agents/{agent_slug}/services/{service_slug}"): "archive",
}


def _api_routes(router):
    """Every APIRoute reachable from an app or router.

    Walks FastAPI's `_IncludedRouter` wrappers, which hold the real router on
    `original_router`. Without this, `app.routes` reports five entries and none
    of them are endpoints, which reads like an empty application.
    """
    out = []
    for route in getattr(router, "routes", []) or []:
        if type(route).__name__ == "_IncludedRouter":
            out.extend(_api_routes(route.original_router))
        elif hasattr(route, "dependant") and getattr(route, "methods", None):
            out.append(route)
    return out


def _required_scopes(route) -> set[str]:
    """The scopes a route enforces, read from the dependency tree.

    Taken from the built application rather than by reading the routers,
    because the question is what the served app requires. A decorator that was
    edited but never wired would still look right in the source.
    """
    found: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        for cell in getattr(getattr(dep, "call", None), "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:  # pragma: no cover - an empty cell
                continue
            if isinstance(value, frozenset) and value and all(
                isinstance(item, str) and ":" in item for item in value
            ):
                found |= value
        stack.extend(dep.dependencies)
    return found


def _write_endpoints() -> set[tuple[str, str]]:
    prefix = "/api/v1"
    out = set()
    for route in _api_routes(app):
        if any(s.endswith(":write") for s in _required_scopes(route)):
            path = route.path
            out.add((sorted(route.methods)[0], path[len(prefix):] if path.startswith(prefix) else path))
    return out


def test_every_write_endpoint_has_a_recorded_sdk_position() -> None:
    """A new write endpoint must not quietly land outside every client.

    This is the check that would have caught the original gap the day it
    appeared rather than after the scopes shipped.
    """
    actual = _write_endpoints()
    assert actual, "no write-scoped endpoints were found, so this test is checking nothing"

    recorded = set(SDK_WRITE_COVERAGE)
    assert actual == recorded, (
        "the write endpoints and their recorded SDK position disagree.\n"
        f"  enforced but unrecorded: {sorted(actual - recorded)}\n"
        f"  recorded but not enforced: {sorted(recorded - actual)}\n"
        "Add the endpoint to SDK_WRITE_COVERAGE with either the client method "
        "that covers it or None and the reason it is deliberately absent."
    )


# Each language spells the same operation differently. The canonical name is
# snake_case, and these turn it into what the source of each client should
# contain. Checked as source text rather than by importing, because the Go and
# TypeScript clients cannot be imported from a Python test.
def _spellings(canonical: str) -> dict[str, str]:
    parts = canonical.split("_")
    camel = parts[0] + "".join(p.title() for p in parts[1:])
    pascal = "".join(p.title() for p in parts)
    return {
        "python": rf"\bdef {canonical}\(",
        "typescript": rf"\b{camel}\(",
        "go": rf"\)\s+{pascal}\(",
    }


_SDK_SOURCES = {
    "python": SDK_ROOT / "python" / "src" / "agoreum" / "async_client.py",
    "typescript": SDK_ROOT / "typescript" / "src" / "client.ts",
    "go": SDK_ROOT / "go",
}


def _source_text(language: str) -> str:
    target = _SDK_SOURCES[language]
    if target.is_dir():
        return "\n".join(
            f.read_text(encoding="utf-8") for f in sorted(target.glob("*.go"))
            if not f.name.endswith("_test.go")
        )
    return target.read_text(encoding="utf-8")


def test_covered_endpoints_really_exist_in_every_sdk() -> None:
    """The three clients are documented as mirroring each other.

    A method present in one and missing from another is the divergence that
    claim rules out, and it would otherwise only surface for whichever language
    a user happened to pick.
    """
    covered = sorted({m for m in SDK_WRITE_COVERAGE.values() if m})
    assert covered, "no endpoint is recorded as covered, so this test is checking nothing"

    missing = []
    for language in _SDK_SOURCES:
        text = _source_text(language)
        for method in covered:
            if not re.search(_spellings(method)[language], text):
                missing.append(f"{language}: {method}")

    assert not missing, (
        "an endpoint recorded as covered has no method in that client:\n  "
        + "\n  ".join(missing)
    )


# --- Method as well as path ---------------------------------------------------
#
# The checks above compare paths only, and that is how a second SDK defect of
# the original shape reached production. All three clients called
# `GET /agents` for "list the agents I own". The API serves `POST /agents` and
# `GET /agents/mine`, so every call returned 405 Method Not Allowed. The path
# check passed because `/agents` is a real path, just not for that verb.
#
# One near miss is a bug. The same shape twice is the guard being aimed slightly
# short, so this compares the pair.
#
# Only calls where the verb sits next to the path are read, which is every call
# in all three clients: they route through one request helper that takes the
# method first.
_CALLS = {
    # request("GET", "/agents/mine")
    "python": re.compile(r'request\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*f?"([^"]+)"'),
    # request<T>("GET", "/agents/mine")
    "typescript": re.compile(
        r'request(?:<[^>]*>)?\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*[`"]([^`"]+)[`"]'
    ),
    # doJSON[T](ctx, c, http.MethodGet, "/agents/mine", ...)
    "go": re.compile(r'http\.Method(Get|Post|Put|Patch|Delete)\s*,\s*"([^"]+)"'),
}


# `_join_concatenations` only collapses a parameter with a literal on both sides.
# Go ends several paths with one: `"/agents/" + url.PathEscape(slug)`. Left
# alone that reads as the literal `/agents/`, which normalises to `/agents`, and
# this check then reports `GET /agents` as wrong when the client is correct.
#
# It did exactly that on its first run. The finding was a defect in the
# measurement, not in the client, and reporting it would have sent someone to
# fix working code.
_TRAILING_CONCAT = re.compile(r'"([^"]*)"\s*\+\s*[A-Za-z_][\w.]*\(')


def _join_trailing(text: str) -> str:
    """Turn `"/agents/" + escape(x)` into the literal `"/agents/{}"`."""
    return _TRAILING_CONCAT.sub(lambda m: f'"{m.group(1)}{{}}" (', text)


def _served_pairs() -> set[tuple[str, str]]:
    prefix = "/api/v1"
    out = set()
    for route in _api_routes(app):
        path = route.path
        path = path[len(prefix):] if path.startswith(prefix) else path
        for method in route.methods:
            if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.add((method, _normalise(path)))
    return out


@pytest.mark.parametrize("language", ["python", "typescript", "go"])
def test_every_sdk_call_matches_a_real_method_and_path(language: str) -> None:
    served = _served_pairs()
    assert served, "no routes were found, so this test is checking nothing"

    text = _source_text(language)
    calls = {
        (m.group(1).upper(), _normalise(m.group(2)))
        for m in _CALLS[language].finditer(_join_trailing(_join_concatenations(text)))
    }
    assert calls, f"no {language} calls were parsed, so this test is checking nothing"

    wrong = []
    for method, path in sorted(calls):
        if (method, path) in served:
            continue
        others = sorted(m for m, p in served if p == path)
        wrong.append(
            f"{method} {path}"
            + (f"  (served for {', '.join(others)})" if others else "  (no such path)")
        )

    assert not wrong, (
        f"the {language} client calls something this API does not serve:\n  "
        + "\n  ".join(wrong)
    )


# --- Version strings ----------------------------------------------------------
#
# Each client sends its version in the User-Agent. The TypeScript constant said
# 0.1.0 while its package.json said 0.1.1, and the Go constant said 0.1.0 while
# the module was tagged 0.1.1, so both published clients reported themselves as
# a version that had a known broken endpoint path.
#
# That is worse than untidy. The one moment this field earns its keep is asking
# "which version is that broken call coming from", and both would have answered
# with the wrong one.
#
# The comment above the TypeScript constant said "kept in sync with
# package.json". Nothing kept it in sync. That is the same shape as the docs
# page and the scope catalogue: a stated invariant with no check under it.
_VERSION_SOURCES = {
    "python": (SDK_ROOT / "python" / "src" / "agoreum" / "_version.py",
               re.compile(r'__version__ = "([^"]+)"')),
    "typescript": (SDK_ROOT / "typescript" / "src" / "version.ts",
                   re.compile(r'export const VERSION = "([^"]+)"')),
    "typescript-package": (SDK_ROOT / "typescript" / "package.json",
                           re.compile(r'"version":\s*"([^"]+)"')),
    "go": (SDK_ROOT / "go" / "agoreum.go", re.compile(r'const Version = "([^"]+)"')),
}


def test_the_sdks_all_declare_the_same_version() -> None:
    """They are released in lockstep, so a difference is a mistake, not a choice."""
    found = {}
    for name, (path, pattern) in _VERSION_SOURCES.items():
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match, f"no version found in {path.name}, so this test is checking nothing"
        found[name] = match.group(1)

    assert len(set(found.values())) == 1, (
        "the SDK version strings disagree, so at least one client reports a "
        f"version it is not: {found}"
    )
