"""Who may use the operational surface.

The interesting assertions are the refusals. This surface exists to work a dispute
queue and to lift a permanent email suppression, so wrongly granting it is worse
than wrongly withholding it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.modules.admin import service as admin
from app.modules.orders import service as orders

ADMIN = "0x000000000000000000000000000000000000adm1"
ARBITER = "0x00000000000000000000000000000000000ab1e5"


@dataclass
class FakeUser:
    primary_address: str = ADMIN
    id: object = field(default=None)


class TestAdminAuthority:
    def test_the_configured_admin_address_is_admin(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        assert admin.is_platform_admin(FakeUser()) is True

    def test_case_does_not_decide_authority(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN.upper())
        assert admin.is_platform_admin(FakeUser(primary_address=ADMIN)) is True

    def test_anybody_else_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        assert admin.is_platform_admin(FakeUser(primary_address="0xdead")) is False

    def test_unconfigured_means_nobody(self, monkeypatch) -> None:
        """A deployment that forgets this should be closed, not wide open."""
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", None)
        assert admin.is_platform_admin(FakeUser()) is False
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", "")
        assert admin.is_platform_admin(FakeUser(primary_address="")) is False

    def test_an_account_with_no_address_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        assert admin.is_platform_admin(FakeUser(primary_address=None)) is False


class TestTheTwoAuthoritiesAreSeparate:
    def test_an_admin_is_not_automatically_an_arbiter(self, monkeypatch) -> None:
        """They decide different things and are different roles on chain.

        An administrator who is not the arbiter cannot settle anything, so
        conflating them would only invite an attempt that the chain refuses.
        """
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", ARBITER)
        user = FakeUser(primary_address=ADMIN)
        assert admin.is_platform_admin(user) is True
        assert orders.is_arbiter(user) is False

    def test_an_arbiter_is_not_automatically_an_admin(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", ARBITER)
        user = FakeUser(primary_address=ARBITER)
        assert orders.is_arbiter(user) is True
        assert admin.is_platform_admin(user) is False


class TestTheSurfaceIsRegistered:
    def test_the_operational_endpoints_exist(self) -> None:
        """They were listed as a later stage for long enough to be forgotten."""
        from app.main import app

        paths = app.openapi()["paths"]
        assert "get" in paths["/api/v1/admin/disputes"]
        assert "get" in paths["/api/v1/admin/email-suppressions"]
        assert "delete" in paths["/api/v1/admin/email-suppressions/{email}"]
