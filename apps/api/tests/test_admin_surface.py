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


class TestTheSurfaceActuallyResponds:
    """Registered is not reachable, and reachable is not working.

    Everything above this asserts who *may* use the surface and that the routes
    exist in the schema. Nothing called one. Two failures got through that gap
    on the same day, and neither was subtle once seen.

    Production had no `ESCROW_ADMIN_ADDRESS` at all, so `is_platform_admin`
    returned false for every account and the whole operational surface, dispute
    queue included, answered 403 to everybody for its entire life. The gate
    failing closed was correct. Nobody had ever checked that it opened.

    And the exclusion handler raised on its own logging call, because it passed
    context as bare keyword arguments where this project's adapter wants
    `extra=`. Both the reputation filter and the database trigger underneath it
    were thoroughly tested and mutation tested. The one function that calls them
    was not, so a guard can be proven correct while its only caller is broken.

    So this drives the endpoint through the real app.
    """

    async def _admin_token(self, client, monkeypatch) -> str:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        account = Account.create()
        monkeypatch.setattr(
            settings, "ESCROW_ADMIN_ADDRESS", account.address.lower()
        )
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": account.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = account.sign_message(encode_defunct(text=challenge["message"]))
        body = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()
        return body["tokens"]["access_token"]

    async def test_an_unknown_order_is_not_found_rather_than_a_500(
        self, client, monkeypatch
    ) -> None:
        """The narrowest call that still executes the whole handler.

        It reaches the admin gate, the request body validation, the service
        function and its logging, which is every line that was broken, without
        needing a settled order to exist.
        """
        import uuid as _uuid

        token = await self._admin_token(client, monkeypatch)
        response = await client.post(
            f"/api/v1/admin/orders/{_uuid.uuid4()}/exclude-from-reputation",
            json={"reason": "a reason long enough to satisfy the floor"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404, response.text
        assert "internal" not in response.text.lower(), (
            "the handler raised instead of refusing, which is how a logging call "
            "with the wrong argument style reached production"
        )

    async def test_a_reason_is_required(self, client, monkeypatch) -> None:
        """The decision cannot be revisited, so what was written at the time is
        all a future reader will ever have."""
        import uuid as _uuid

        token = await self._admin_token(client, monkeypatch)
        response = await client.post(
            f"/api/v1/admin/orders/{_uuid.uuid4()}/exclude-from-reputation",
            json={"reason": "too short"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422, response.text

    async def test_a_non_admin_is_refused(self, client, monkeypatch) -> None:
        """The control. A test that only ever calls the endpoint as an admin
        would pass just as well if the gate were removed entirely."""
        import uuid as _uuid

        from eth_account import Account
        from eth_account.messages import encode_defunct

        monkeypatch.setattr(settings, "ESCROW_ADMIN_ADDRESS", ADMIN)
        account = Account.create()
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": account.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = account.sign_message(encode_defunct(text=challenge["message"]))
        token = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        response = await client.post(
            f"/api/v1/admin/orders/{_uuid.uuid4()}/exclude-from-reputation",
            json={"reason": "a reason long enough to satisfy the floor"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "not_admin"

    async def test_the_dispute_queue_answers_the_arbiter_not_the_admin(
        self, client, monkeypatch
    ) -> None:
        """Written asserting an admin could open it, which was wrong.

        The queue is gated on the arbiter, and `TestTheTwoAuthoritiesAreSeparate`
        above says why: an admin runs the platform, an arbiter decides who gets
        money, and the second is a role the chain recognises rather than a
        setting. This test failed on its first run with `not_arbiter`, which is
        the code being right and the test being wrong.

        Worth keeping in both directions, because that separation is the kind of
        thing a refactor quietly collapses.
        """
        from eth_account import Account
        from eth_account.messages import encode_defunct

        async def token_for(account) -> str:
            challenge = (
                await client.post(
                    "/api/v1/auth/nonce",
                    json={
                        "address": account.address.lower(),
                        "chain_id": settings.CHAIN_ID,
                    },
                )
            ).json()
            signed = account.sign_message(encode_defunct(text=challenge["message"]))
            body = (
                await client.post(
                    "/api/v1/auth/signin",
                    json={
                        "message": challenge["message"],
                        "signature": signed.signature.hex(),
                        "nonce": challenge["nonce"],
                    },
                )
            ).json()
            return body["tokens"]["access_token"]

        arbiter_account = Account.create()
        admin_account = Account.create()
        monkeypatch.setattr(
            settings, "ESCROW_ARBITER_ADDRESS", arbiter_account.address.lower()
        )
        monkeypatch.setattr(
            settings, "ESCROW_ADMIN_ADDRESS", admin_account.address.lower()
        )

        arbiter_response = await client.get(
            "/api/v1/admin/disputes",
            headers={"Authorization": f"Bearer {await token_for(arbiter_account)}"},
        )
        assert arbiter_response.status_code == 200, arbiter_response.text
        assert isinstance(arbiter_response.json(), list)

        admin_response = await client.get(
            "/api/v1/admin/disputes",
            headers={"Authorization": f"Bearer {await token_for(admin_account)}"},
        )
        assert admin_response.status_code == 403, admin_response.text
        assert admin_response.json()["error"]["code"] == "not_arbiter", (
            "running the platform started granting the power to decide who gets "
            "the money, which is the one separation this surface has"
        )
