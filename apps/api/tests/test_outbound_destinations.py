"""Where the platform is allowed to send an outbound request.

Two places fetch a destination somebody else chose: webhook delivery, and agent
domain verification. Both run inside our network, so both are server-side
request forgery positions. The rule was implemented twice, independently, and
only one copy was tested; this covers the shared one both now use.

The webhook side also has two defences that are not about addresses and are
easy to remove by accident: https only, and redirects not followed. They are
why the cloud metadata service, which speaks plain HTTP, was never reachable.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import outbound
from app.core.outbound import DestinationNotAllowed, assert_public_host, check_host
from app.modules.agents import domain_check
from app.modules.webhooks import destinations

pytestmark = pytest.mark.asyncio

PUBLIC = "93.184.216.34"

FORBIDDEN_LITERALS = [
    "127.0.0.1",
    "10.0.0.5",
    "172.16.0.1",
    "192.168.1.1",
    # The cloud metadata address. Out of reach today only because that service
    # speaks HTTP, which is not a defence anything here controls.
    "169.254.169.254",
    "::1",
    "fd00::1",
    "fe80::1",
    "0.0.0.0",  # noqa: S104  the unspecified address, listed here to be refused
    # IPv4 wearing an IPv6 costume.
    "::ffff:10.0.0.5",
]


class TestTheRuleItself:
    @pytest.mark.parametrize("address", FORBIDDEN_LITERALS)
    async def test_a_private_or_reserved_address_is_forbidden(self, address: str) -> None:
        assert outbound.is_forbidden_address(address) is True

    async def test_a_public_address_is_allowed(self) -> None:
        assert outbound.is_forbidden_address(PUBLIC) is False

    @pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
    async def test_a_literal_is_refused_without_reaching_dns(
        self, literal: str, monkeypatch
    ) -> None:
        """Otherwise `https://10.0.0.5/` would depend on the resolver echoing
        it back, which is not something to rely on."""
        monkeypatch.setattr(
            outbound, "resolved_addresses", lambda *a, **k: pytest.fail("DNS was used")
        )
        with pytest.raises(DestinationNotAllowed):
            await assert_public_host(literal)

    async def test_every_resolved_address_is_checked_not_just_the_first(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [PUBLIC, "10.1.2.3"])
        with pytest.raises(DestinationNotAllowed):
            await assert_public_host("mixed.customer.test")

    async def test_a_public_name_is_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [PUBLIC])
        await assert_public_host("hooks.customer.test")

    async def test_an_unresolvable_name_is_refused_by_default(self, monkeypatch) -> None:
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [])
        with pytest.raises(DestinationNotAllowed):
            await assert_public_host("gone.customer.test")

    async def test_registration_may_accept_an_unresolvable_name(self, monkeypatch) -> None:
        """A name that does not resolve yet is a likelier mistake than an
        attack, and delivery checks again before anything is sent."""
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [])
        await assert_public_host("gone.customer.test", enforce_unresolvable=False)

    async def test_the_lenient_path_still_refuses_a_private_literal(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [])
        with pytest.raises(DestinationNotAllowed):
            await assert_public_host("10.0.0.5", enforce_unresolvable=False)


class TestResolutionDoesNotBlockTheEventLoop:
    """`getaddrinfo` blocks, and this runs inside an async worker.

    The first version of the webhook check called it directly, which would stall
    every other request in the process behind a slow or hostile nameserver. The
    older domain-verification copy had always got this right, which is the
    argument for there being one copy.
    """

    async def test_resolution_is_moved_off_the_loop(self, monkeypatch) -> None:
        used = []
        real = asyncio.to_thread

        async def recording(func, *args, **kwargs):
            used.append(func.__name__)
            return await real(func, *args, **kwargs)

        monkeypatch.setattr(outbound.asyncio, "to_thread", recording)
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [PUBLIC])
        await assert_public_host("hooks.customer.test")
        assert used == ["<lambda>"], "resolution ran on the event loop"


class TestBothCallersUseIt:
    async def test_a_webhook_url_with_no_host_is_refused(self) -> None:
        with pytest.raises(DestinationNotAllowed):
            await destinations.assert_allowed("https:///nowhere")

    async def test_a_webhook_url_is_judged_by_its_host(self, monkeypatch) -> None:
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: ["10.1.2.3"])
        with pytest.raises(DestinationNotAllowed):
            await destinations.assert_allowed("https://hooks.customer.test/path")

    async def test_domain_verification_uses_the_same_rule(self, monkeypatch) -> None:
        """It reports rather than raises, because it answers a person filling in
        a form, but the judgement underneath is the shared one."""
        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: ["10.1.2.3"])
        allowed, reason = domain_check._is_public_address("customer.test")
        assert allowed is False
        assert reason

        monkeypatch.setattr(outbound, "resolved_addresses", lambda *a, **k: [PUBLIC])
        assert check_host("customer.test") == (True, None)
