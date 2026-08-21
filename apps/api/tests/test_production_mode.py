"""Controls that only exist in production, and were therefore never tested.

`APP_ENV` is `test` in CI and `development` locally, so every branch guarded by
`settings.is_production` is dead code as far as the suite is concerned. Three of
them are security controls, and each fails in a direction nobody would notice
from a passing suite.

This is the same shape as the logging blind spot found on 2026-08-21: the suite
is configured differently from production, so it does not test production. That
one hid a `TypeError` for the life of an endpoint. These hide the sign-in chain
policy, the transport security header, and the Host header defence.

None of this needs a production deployment. `create_app()` and the middleware
are constructed at call time, so flipping the setting and building them is
enough to execute the real branch.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture
def in_production(monkeypatch):
    """Run the code under test as production sees it."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert settings.is_production, "the fixture did not actually flip the mode"
    return settings


class TestSignInChainPolicyNarrowsInProduction:
    """Which chains this deployment will accept a signature from.

    Outside production the verifier also accepts Base mainnet and Base Sepolia so
    the flow can be exercised on testnet. In production it accepts exactly the
    configured chain and nothing else.

    The existing test asserted `CHAIN_ID in accepted_chain_ids()`, which is true
    in both branches and so could never have caught the narrowing being lost. A
    deployment that kept the permissive set would accept a signature produced for
    a different chain, which is the whole reason the chain id is in the signed
    message.
    """

    def test_production_accepts_only_the_configured_chain(self, in_production) -> None:
        from app.modules.auth import siwe_verifier

        accepted = siwe_verifier.accepted_chain_ids()
        assert accepted == {settings.CHAIN_ID}, accepted

        others = {siwe_verifier.BASE_MAINNET, siwe_verifier.BASE_SEPOLIA} - {
            settings.CHAIN_ID
        }
        assert not (accepted & others), (
            f"production accepted chains it is not deployed on: {accepted & others}. "
            "A signature carries the chain id it was produced for, so accepting "
            "extra chains accepts signatures meant for another deployment."
        )

    def test_outside_production_the_testnet_is_accepted(self, monkeypatch) -> None:
        """The control. Without this, narrowing to the empty set would pass."""
        from app.modules.auth import siwe_verifier

        monkeypatch.setattr(settings, "APP_ENV", "development")
        accepted = siwe_verifier.accepted_chain_ids()
        assert siwe_verifier.BASE_SEPOLIA in accepted
        assert settings.CHAIN_ID in accepted


class TestTransportSecurityIsSetInProduction:
    """HSTS is added only in production, and only at construction time.

    Built in `__init__`, so the header set is decided once when the app is
    created. Nothing asserted it was ever decided correctly.
    """

    def test_hsts_is_present_and_long_lived(self, in_production) -> None:
        from app.core.middleware import SecurityHeadersMiddleware

        middleware = SecurityHeadersMiddleware(app=None)
        value = middleware._headers.get("Strict-Transport-Security")

        assert value, "production serves no Strict-Transport-Security header"
        assert "includeSubDomains" in value
        max_age = int(value.split("max-age=")[1].split(";")[0])
        assert max_age >= 31536000, (
            f"max-age is {max_age}s, under a year, which is below what preload "
            "lists require and short enough to leave a downgrade window"
        )

    def test_it_is_absent_outside_production(self, monkeypatch) -> None:
        """The control, and it is not pedantry.

        HSTS on a development host pins it to HTTPS in the developer's browser
        for the max-age above, which is a year of a local http:// origin being
        unreachable and very hard to diagnose.
        """
        from app.core.middleware import SecurityHeadersMiddleware

        monkeypatch.setattr(settings, "APP_ENV", "development")
        middleware = SecurityHeadersMiddleware(app=None)
        assert "Strict-Transport-Security" not in middleware._headers

    def test_the_always_on_headers_do_not_depend_on_the_mode(self, monkeypatch) -> None:
        """The headers that are not conditional must not become conditional."""
        from app.core.middleware import SecurityHeadersMiddleware

        required = {
            "X-Content-Type-Options",
            "Referrer-Policy",
            "Content-Security-Policy",
            "Cross-Origin-Opener-Policy",
        }
        for mode in ("production", "development", "test"):
            monkeypatch.setattr(settings, "APP_ENV", mode)
            headers = set(SecurityHeadersMiddleware(app=None)._headers)
            assert required <= headers, f"{mode} is missing {required - headers}"


class TestHostHeaderDefenceInProduction:
    """TrustedHostMiddleware is installed only in production.

    It fails in the loudest possible direction: a hostname missing from the
    allowed set answers 400 for every request to it, which is why the source
    comment insists the internal names are essential rather than optional. The
    container healthcheck reaches the app as 127.0.0.1 and the web container
    calls it as `api`, so dropping either takes production down while every test
    stays green.
    """

    def test_the_middleware_is_installed(self, in_production) -> None:
        from app.main import create_app

        app = create_app()
        names = [m.cls.__name__ for m in app.user_middleware]
        assert "TrustedHostMiddleware" in names, (
            f"production builds no Host header defence. Installed: {names}"
        )

    def test_it_admits_the_names_production_actually_uses(self, in_production) -> None:
        from app.main import create_app

        app = create_app()
        trusted = next(
            m for m in app.user_middleware if m.cls.__name__ == "TrustedHostMiddleware"
        )
        allowed = set(trusted.kwargs.get("allowed_hosts") or [])

        # Both are load bearing and neither is externally visible, so losing one
        # is invisible until production stops answering.
        assert "127.0.0.1" in allowed, (
            "the container healthcheck reaches the app as 127.0.0.1; without it "
            "every health probe answers 400 and the container is marked unhealthy"
        )
        assert "api" in allowed, (
            "server-side rendering in the web container calls the API as `api` "
            "over the compose network; without it every page render fails"
        )

        public = settings.SIWE_DOMAIN.split(":")[0]
        assert any(public in host for host in allowed), (
            f"no allowed host derives from SIWE_DOMAIN ({public}): {allowed}"
        )

    def test_it_is_absent_outside_production(self, monkeypatch) -> None:
        from app.main import create_app

        monkeypatch.setattr(settings, "APP_ENV", "development")
        app = create_app()
        names = [m.cls.__name__ for m in app.user_middleware]
        assert "TrustedHostMiddleware" not in names
