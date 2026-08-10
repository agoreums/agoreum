"""Where a webhook may point.

The delivery worker runs inside our network and fetches a URL the customer
chose, which is the classic server-side request forgery position. Two defences
already existed and both matter: https only, and redirects not followed. They
are why the cloud metadata service, which speaks plain HTTP, was never
reachable.

Neither is about addresses. That protection was a side effect of one service's
choice of protocol rather than a decision, and the delivery record hands
`last_status_code` and `last_error` back to the organization, so the worker
doubles as an oracle for probing the private network. These assert the decision.
"""
from __future__ import annotations

import pytest

from app.modules.webhooks import destinations
from app.modules.webhooks.destinations import DestinationNotAllowed, assert_allowed


class TestAddressLiteralsAreRefusedWithoutTouchingDns:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/hook",
            "https://10.0.0.5/hook",
            "https://172.16.0.1/hook",
            "https://192.168.1.1/hook",
            # The cloud metadata address. Out of reach today only because that
            # service speaks HTTP, which is not a defence we control.
            "https://169.254.169.254/latest/meta-data/",
            "https://[::1]/hook",
            "https://[fd00::1]/hook",
            "https://[fe80::1]/hook",
            "https://0.0.0.0/hook",
            # IPv4 wearing an IPv6 costume.
            "https://[::ffff:10.0.0.5]/hook",
        ],
    )
    def test_a_private_or_reserved_literal_is_refused(self, url: str) -> None:
        with pytest.raises(DestinationNotAllowed):
            assert_allowed(url)

    def test_a_public_literal_is_allowed(self) -> None:
        assert_allowed("https://93.184.216.34/hook")


class TestNamesAreCheckedByWhatTheyResolveTo:
    def test_a_name_resolving_to_a_private_address_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(destinations, "resolved_addresses", lambda h: ["10.1.2.3"])
        with pytest.raises(DestinationNotAllowed):
            assert_allowed("https://hooks.customer.test/x")

    def test_a_name_resolving_to_a_public_address_is_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(destinations, "resolved_addresses", lambda h: ["93.184.216.34"])
        assert_allowed("https://hooks.customer.test/x")

    def test_every_address_is_checked_not_just_the_first(self, monkeypatch) -> None:
        """A name answering with one public and one private address would
        otherwise pass, and the client would connect to whichever it chose."""
        monkeypatch.setattr(
            destinations, "resolved_addresses", lambda h: ["93.184.216.34", "10.1.2.3"]
        )
        with pytest.raises(DestinationNotAllowed):
            assert_allowed("https://hooks.customer.test/x")


class TestUnresolvableNames:
    def test_delivery_refuses_a_name_that_does_not_resolve(self, monkeypatch) -> None:
        monkeypatch.setattr(destinations, "resolved_addresses", lambda h: [])
        with pytest.raises(DestinationNotAllowed):
            assert_allowed("https://gone.customer.test/x")

    def test_registration_tolerates_it(self, monkeypatch) -> None:
        """A name that does not resolve yet is a plausible mistake rather than
        an attack, and delivery checks again before anything is sent."""
        monkeypatch.setattr(destinations, "resolved_addresses", lambda h: [])
        assert_allowed("https://gone.customer.test/x", enforce_unresolvable=False)

    def test_registration_still_refuses_a_private_literal(self, monkeypatch) -> None:
        """The lenient flag must not become a way in."""
        monkeypatch.setattr(destinations, "resolved_addresses", lambda h: [])
        with pytest.raises(DestinationNotAllowed):
            assert_allowed("https://10.0.0.5/x", enforce_unresolvable=False)


def test_a_url_with_no_host_is_refused() -> None:
    with pytest.raises(DestinationNotAllowed):
        assert_allowed("https:///nowhere")
