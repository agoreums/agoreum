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
