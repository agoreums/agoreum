"""Who a rate limit is counted against.

The quota is only as good as the identity behind it. Two defects lived here, and
both were invisible because the limiter still returned a number and the endpoint
still worked.

The identity is also the only thing standing between `auth:verify-email` and
being a way to mail a stranger repeatedly, so it is worth asserting directly
rather than through an endpoint.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core import security
from app.core.rate_limit import client_identity, rate_limit_scope


def _request(*, headers: dict[str, str] | None = None, user_id: str | None = None):
    """A request stand-in carrying only what the identity function reads."""
    state = SimpleNamespace()
    if user_id is not None:
        state.user_id = user_id
    return SimpleNamespace(headers=headers or {}, state=state, client=None)


def _api_routes(router):
    """Every route with a resolved dependency tree, through FastAPI's wrappers."""
    out = []
    for route in getattr(router, "routes", []) or []:
        if type(route).__name__ == "_IncludedRouter":
            out.extend(_api_routes(route.original_router))
        elif hasattr(route, "dependant") and getattr(route, "methods", None):
            out.append(route)
    return out


def _is_limiter(call) -> bool:
    # `limiter(bucket)` returns a closure named `limiter.<locals>.dependency`.
    return getattr(call, "__qualname__", "").startswith("limiter.")


def misplaced_limiters(app) -> list[str]:
    """Routes whose limiter is a path parameter rather than a route dependency.

    Deliberately one function rather than one per caller. An earlier version had
    the assertion and the test proving the assertion works carry separate copies
    of this logic, so blinding the first left the second green, which is the
    exact shape of defect this file exists to catch.
    """
    found = []
    for route in _api_routes(app):
        declared = {
            id(getattr(dep, "dependency", None))
            for dep in (getattr(route, "dependencies", []) or [])
        }
        for dep in route.dependant.dependencies:
            if _is_limiter(getattr(dep, "call", None)) and id(dep.call) not in declared:
                found.append(f"{sorted(route.methods)[0]} {route.path}")
    return found


def count_limiters(app) -> int:
    return sum(
        1
        for route in _api_routes(app)
        for dep in route.dependant.dependencies
        if _is_limiter(getattr(dep, "call", None))
    )


class TestAnAddressIsNarrowedToWhatACallerCannotChange:
    def test_ipv4_is_counted_whole(self) -> None:
        assert rate_limit_scope("203.0.113.9") == "203.0.113.9"

    def test_two_addresses_in_one_ipv6_allocation_share_a_bucket(self) -> None:
        """The defect this closes.

        A residential IPv6 allocation is typically a /64. Counting per address
        let one client hold eighteen quintillion quotas, so every limit was
        unenforced for anyone on IPv6.
        """
        first = rate_limit_scope("2a0e:1d47:cb9a:6300:4de6:bfbd:7b46:ac45")
        second = rate_limit_scope("2a0e:1d47:cb9a:6300:ffff:ffff:ffff:ffff")
        assert first == second == "2a0e:1d47:cb9a:6300::/64"

    def test_a_neighbouring_allocation_is_a_different_bucket(self) -> None:
        """Narrowing must not go so far that unrelated people share a quota."""
        assert rate_limit_scope("2a0e:1d47:cb9a:6300::1") != rate_limit_scope(
            "2a0e:1d47:cb9a:6301::1"
        )

    def test_an_ipv4_mapped_address_is_treated_as_ipv4(self) -> None:
        """Otherwise an IPv4 client arriving in mapped form would be collapsed
        into a /64 shared with every other mapped address."""
        assert rate_limit_scope("::ffff:203.0.113.9") == "203.0.113.9"

    def test_something_unparseable_is_passed_through_not_guessed_at(self) -> None:
        assert rate_limit_scope("unknown") == "unknown"


class TestAnAuthenticatedCallerIsCountedByAccount:
    """The second defect, and the subtler one.

    Limiters are declared as route-level dependencies, and FastAPI resolves
    those before the path function's own parameters, so the limiter ran before
    anything had set `request.state.user_id`. Every authenticated route
    therefore used the IP bucket while the code documented the opposite.
    """

    def test_state_is_used_when_something_already_resolved_the_user(self) -> None:
        assert client_identity(_request(user_id="abc")) == "user:abc"

    def test_a_bearer_token_identifies_the_account_without_request_state(self) -> None:
        user_id = uuid.uuid4()
        token, _ = security.create_access_token(
            user_id=user_id, address="0xabc", role="user", session_id=uuid.uuid4()
        )
        request = _request(headers={"Authorization": f"Bearer {token}"})
        assert client_identity(request) == f"user:{user_id}"

    def test_the_same_account_from_two_addresses_shares_one_quota(self) -> None:
        """Rotating addresses must not reset an account's allowance."""
        user_id = uuid.uuid4()
        token, _ = security.create_access_token(
            user_id=user_id, address="0xabc", role="user", session_id=uuid.uuid4()
        )
        one = _request(
            headers={"Authorization": f"Bearer {token}", "CF-Connecting-IP": "203.0.113.1"}
        )
        two = _request(
            headers={"Authorization": f"Bearer {token}", "CF-Connecting-IP": "198.51.100.2"}
        )
        assert client_identity(one) == client_identity(two) == f"user:{user_id}"

    @pytest.mark.parametrize(
        "header",
        [
            "Bearer not-a-token",
            "Bearer ",
            "Basic abc",
            "",
        ],
    )
    def test_an_unusable_token_falls_back_to_the_address(self, header: str) -> None:
        """A stale browser token must not raise here. Refusing the request is
        the authentication layer's job, and endpoints that allow anonymous use
        would otherwise start failing."""
        request = _request(
            headers={"Authorization": header, "CF-Connecting-IP": "203.0.113.7"}
        )
        assert client_identity(request) == "ip:203.0.113.7"

    def test_an_anonymous_caller_on_ipv6_is_counted_by_allocation(self) -> None:
        request = _request(
            headers={"CF-Connecting-IP": "2a0e:1d47:cb9a:6300:4de6:bfbd:7b46:ac45"}
        )
        assert client_identity(request) == "ip:2a0e:1d47:cb9a:6300::/64"


class TestAProgrammaticCallerIsCountedByKey:
    """The third defect that lived here, and the one that hid best.

    `get_principal` sets `request.state.user_id` for key traffic under a comment
    saying keys are counted by account. They were not. Limiters are route-level
    dependencies and FastAPI resolves those before a path function's own
    parameters, so the limiter has already run by the time that line executes,
    which is the exact ordering trap `client_identity` documents at length a few
    lines further up the same file.

    So the code named the right thing, in the right place, with a comment
    asserting the outcome, and could not deliver it. Two unrelated customers
    calling from one cloud provider's address shared a quota, and moving address
    reset a key's quota, both of which this module documents as impossible.
    """

    def test_a_key_is_not_counted_against_its_address(self) -> None:
        key = security.generate_api_key()
        identity = client_identity(_request(headers={"X-API-Key": key}))
        assert identity.startswith("key:"), identity

    def test_two_keys_from_one_address_do_not_share_a_quota(self) -> None:
        """The failure that reached real callers.

        Integrations run from a handful of cloud providers, so "same address,
        different customer" is the normal case rather than an edge one.
        """
        first = client_identity(_request(headers={"X-API-Key": security.generate_api_key()}))
        second = client_identity(_request(headers={"X-API-Key": security.generate_api_key()}))
        assert first != second

    def test_a_key_is_recognised_however_it_is_presented(self) -> None:
        """Both forms are accepted by the authentication layer, so a caller must
        not get a second quota by switching header."""
        key = security.generate_api_key()
        assert client_identity(
            _request(headers={"X-API-Key": key})
        ) == client_identity(_request(headers={"Authorization": f"Bearer {key}"}))

    def test_changing_address_does_not_reset_a_key_quota(self) -> None:
        key = security.generate_api_key()
        one = SimpleNamespace(
            headers={"X-API-Key": key},
            state=SimpleNamespace(),
            client=SimpleNamespace(host="203.0.113.9"),
        )
        two = SimpleNamespace(
            headers={"X-API-Key": key},
            state=SimpleNamespace(),
            client=SimpleNamespace(host="198.51.100.4"),
        )
        assert client_identity(one) == client_identity(two)

    def test_the_secret_never_becomes_the_bucket_name(self) -> None:
        """The bucket reaches Redis key names, logs and error context. A live
        credential must not travel with it."""
        key = security.generate_api_key()
        identity = client_identity(_request(headers={"X-API-Key": key}))
        assert key not in identity
        assert identity == f"key:{security.hash_token(key)[:32]}"

    def test_a_bearer_token_that_is_not_a_key_is_left_alone(self) -> None:
        """A session JWT must still resolve to its account, not to a key bucket."""
        user_id = uuid.uuid4()
        token, _ = security.create_access_token(
            user_id=user_id,
            address="0x" + "1" * 40,
            role="user",
            session_id=uuid.uuid4(),
        )
        identity = client_identity(_request(headers={"Authorization": f"Bearer {token}"}))
        assert identity == f"user:{user_id}"

    def test_a_session_outranks_a_key_when_both_are_present(self) -> None:
        """An account is the broader unit, so it wins. Otherwise a caller could
        widen their own quota by attaching a key to a browser request."""
        key = security.generate_api_key()
        identity = client_identity(
            _request(headers={"X-API-Key": key}, user_id="abc")
        )
        assert identity == "user:abc"

    def test_something_that_only_looks_like_a_key_falls_back_to_the_address(self) -> None:
        request = SimpleNamespace(
            headers={"X-API-Key": "not-a-key"},
            state=SimpleNamespace(),
            client=SimpleNamespace(host="203.0.113.9"),
        )
        assert client_identity(request) == "ip:203.0.113.9"


class TestTheAssumptionTheIdentityLogicRestsOn:
    """Every limiter must be attached as a route-level dependency.

    This is the load-bearing assumption underneath both defects above, and it
    was never written down anywhere a change could trip over it.

    FastAPI resolves route-level dependencies before a path function's own
    parameters. That ordering is why `client_identity` reads the bearer token
    and the API key header directly instead of trusting request state, and it is
    why two separate attempts to set `request.state.user_id` during
    authentication achieved nothing.

    Attach a limiter as a path parameter instead and the ordering inverts.
    Authentication would run first, `request.state.user_id` would be set, and
    that branch would start winning. Sessions would land in the same bucket
    either way, so nothing would look wrong. API keys would silently move from
    a per-key quota to a per-account one, quietly merging the quotas of every
    key an account holds, and the only signal would be a limit behaving
    differently than documented.

    So the assumption is asserted rather than described.
    """

    def test_every_limiter_is_attached_at_route_level(self) -> None:
        from app.main import app

        found = count_limiters(app)
        assert found, (
            "no limiters were found at all, so this test is checking nothing. "
            "Either they were removed, or `limiter` was renamed and the qualname "
            "check no longer recognises it."
        )

        misplaced = misplaced_limiters(app)
        assert not misplaced, (
            "a limiter is attached as a path parameter rather than a route-level "
            "dependency, which inverts its ordering against authentication and "
            "silently changes which bucket an API key is counted in: "
            + ", ".join(sorted(set(misplaced)))
        )

    def test_this_check_can_actually_tell_the_two_apart(self) -> None:
        """Guards the guard, and it needed guarding.

        The first attempt to mutation test the assertion above moved a real
        limiter onto a path parameter and the suite stayed green. The mutation
        was the thing that was broken: the router uses lazy annotations and does
        not import `Annotated`, so the annotation never resolved and FastAPI
        dropped the parameter altogether. The result was a route with no limiter
        at all, which is not the case being tested, and it looked exactly like a
        guard that had nothing to complain about.

        So the detection is exercised here against an application built for the
        purpose, with one limiter attached each way. If this ever stops
        distinguishing them, the assertion above is decorative and this says so
        rather than passing quietly.
        """
        from fastapi import Depends, FastAPI

        def fake_limiter():
            async def dependency() -> None:
                return None

            # `limiter(bucket)` produces exactly this qualname, which is what
            # the check recognises.
            dependency.__qualname__ = "limiter.<locals>.dependency"
            return dependency

        probe = FastAPI()

        @probe.get("/route-level", dependencies=[Depends(fake_limiter())])
        async def _route_level() -> dict:
            return {}

        # The default-value form on purpose. This module uses lazy annotations,
        # so an `Annotated[...]` parameter is a string FastAPI has to resolve,
        # and it silently drops the parameter when it cannot. That is precisely
        # how the first mutation of this check managed to test nothing.
        @probe.get("/param-level")
        async def _param_level(_rl=Depends(fake_limiter())) -> dict:
            return {}

        assert count_limiters(probe) == 2, "both limiters must be wired to prove anything"
        flagged = misplaced_limiters(probe)

        assert flagged == ["GET /param-level"], flagged

    def test_the_state_branch_is_unreachable_today_and_that_is_deliberate(self) -> None:
        """Documents why a tested branch never runs in production.

        `client_identity` prefers `request.state.user_id`, and given the
        assertion above nothing has set it by the time a limiter runs. The
        branch is kept because it is correct for a limiter applied after
        authentication, and removing it would leave a future one silently
        counting an authenticated caller by address. Its unreachability is a
        property of how limiters are currently wired, not of the branch.
        """
        assert client_identity(_request(user_id="abc")) == "user:abc"


# Every endpoint reachable with a write scope, and whether it carries a
# per-identity limit.
#
# Two of these were missing until 2026-08-15, both dispute endpoints, both
# appending a row to the order's timeline on every call with no cap. That
# timeline is the record an arbiter reads to decide who gets the money, so
# flooding it degrades the process the escrow depends on, and it does so against
# the other party rather than against us.
#
# They were missing under a comment in the bucket table reading "writes that
# create durable records", which is exactly what they are. Nginx bounded them
# per address, and this layer exists because an address is something a caller
# can change.
#
# The value is the bucket name, or None with the reason a limit is not needed.
# A new write endpoint cannot be added without someone deciding which.
WRITE_ENDPOINT_LIMITS: dict[tuple[str, str], str | None] = {
    ("POST", "/agents"): "agents:create",
    ("POST", "/agents/{agent_slug}/services"): "services:create",
    ("POST", "/orders"): "orders:create",
    ("POST", "/orders/{order_id}/dispute-intent"): "orders:dispute_intent",
    ("POST", "/orders/{order_id}/dispute-statements"): "orders:dispute_statement",
    ("POST", "/agents/{slug}/domain-challenges/{challenge_id}/verify"): "agents:verify_domain",
    ("POST", "/agents/{slug}/github-challenges/{challenge_id}/verify"): "agents:verify_github",
    # State changes on a resource the caller already owns, creating no new rows.
    # The number of agents and services is already bounded by the create limits
    # above, so there is a ceiling on how much there is to toggle.
    ("PATCH", "/agents/{slug}"): None,
    ("POST", "/agents/{slug}/publish"): None,
    ("POST", "/agents/{slug}/pause"): None,
    ("PUT", "/agents/{slug}/payout-wallet"): None,
    ("PATCH", "/agents/{agent_slug}/services/{service_slug}"): None,
    ("POST", "/agents/{agent_slug}/services/{service_slug}/publish"): None,
    ("POST", "/agents/{agent_slug}/services/{service_slug}/availability"): None,
    ("DELETE", "/agents/{agent_slug}/services/{service_slug}"): None,
    # One-way transitions on a single order. Each can succeed at most once,
    # because the second call finds the order already in the next state.
    ("POST", "/orders/{order_id}/start"): None,
    ("POST", "/orders/{order_id}/deliver"): None,
    # Arbiter only, and terminal for the dispute.
    ("POST", "/orders/{order_id}/dispute-decision"): None,
}


def _write_scoped_routes(app):
    """Routes reachable with a write scope, and the bucket each limits on."""
    prefix = "/api/v1"
    found = {}
    for route in _api_routes(app):
        scopes = set()
        bucket = None
        stack = list(route.dependant.dependencies)
        while stack:
            dep = stack.pop()
            call = getattr(dep, "call", None)
            for cell in getattr(call, "__closure__", None) or ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, frozenset) and value and all(
                    isinstance(i, str) and ":" in i for i in value
                ):
                    scopes |= value
                elif _is_limiter(call) and isinstance(value, str):
                    bucket = value
            stack.extend(dep.dependencies)
        if any(s.endswith(":write") for s in scopes):
            path = route.path
            path = path[len(prefix):] if path.startswith(prefix) else path
            found[(sorted(route.methods)[0], path)] = bucket
    return found


class TestEveryWriteEndpointHasADecisionAboutLimiting:
    def test_the_table_matches_the_application(self) -> None:
        from app.main import app

        actual = _write_scoped_routes(app)
        assert actual, "no write-scoped routes found, so this test checks nothing"

        recorded = set(WRITE_ENDPOINT_LIMITS)
        assert set(actual) == recorded, (
            "the write endpoints and their recorded rate limit position disagree.\n"
            f"  reachable but unrecorded: {sorted(set(actual) - recorded)}\n"
            f"  recorded but not reachable: {sorted(recorded - set(actual))}\n"
            "Add the endpoint to WRITE_ENDPOINT_LIMITS with either its bucket "
            "name or None and the reason a limit is not needed."
        )

    def test_every_endpoint_recorded_as_limited_really_is(self) -> None:
        from app.main import app

        actual = _write_scoped_routes(app)
        wrong = []
        for key, expected in WRITE_ENDPOINT_LIMITS.items():
            if expected is None:
                continue
            got = actual.get(key)
            if got != expected:
                wrong.append(f"{key[0]} {key[1]}: expected {expected!r}, found {got!r}")

        assert not wrong, "an endpoint is not limited by the bucket recorded for it:\n  " + "\n  ".join(wrong)

    def test_every_named_bucket_is_configured(self) -> None:
        """A limiter naming a bucket with no configured limit is not a limit."""
        from app.core.rate_limit import LIMITS

        missing = [
            bucket
            for bucket in WRITE_ENDPOINT_LIMITS.values()
            if bucket is not None and bucket not in LIMITS
        ]
        assert not missing, f"buckets used but never configured: {missing}"
